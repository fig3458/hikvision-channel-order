# AIGC START
"""Hikvision NVR digital-channel placement via ISAPI (digest/basic auth)."""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import (
    HTTPBasicAuthHandler,
    HTTPDigestAuthHandler,
    HTTPPasswordMgrWithDefaultRealm,
    Request,
    build_opener,
)
from xml.sax.saxutils import escape as xml_escape

IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
CHANNEL_RE = re.compile(r"^[Dd](\d+)$")
SKIP_CHANNEL_MARKERS = ("待分配", "删到", "删除到")
ALREADY_ADDED_MARKERS = (
    "already",
    "exist",
    "has been added",
    "deviceexist",
    "device exist",
    "networksourceipalreadyexist",
    "设备已添加",
    "已存在",
    "已添加",
    "重复添加",
)

LogFn = Callable[[str], None]


@dataclass
class Assignment:
    ip: str
    name: str
    channel_id: int
    raw_line: str = ""


@dataclass
class LiveChannel:
    channel_id: int
    ip: str
    name: str
    protocol: str = ""


@dataclass
class ParseResult:
    items: list[Assignment]
    skipped: list[str]
    warnings: list[str]


@dataclass
class NvrOptions:
    base_url: str
    nvr_user: str
    nvr_password: str
    cam_user: str
    cam_password: str
    protocol: str = "HIKVISION"
    cam_port: int = 8000
    timeout: float = 25.0
    src_input_port: int = 1
    settle_seconds: float = 3.0
    # 数字通道号扫描起点（混合机可改成模拟通道数+1）
    digital_start: int = 1


@dataclass
class ApplyStats:
    ok: int = 0
    skip: int = 0
    fail: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class GapIssue:
    target: int
    next_free: int
    ip: str
    detail: str


@dataclass
class OrderPlan:
    items: list[Assignment]
    gaps: list[GapIssue]
    notes: list[str]


def normalize_base_url(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("录像机地址不能为空")
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    if not parsed.hostname:
        raise ValueError("录像机地址无效")
    base = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        base += f":{parsed.port}"
    return base


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _find_text(el: ET.Element, names: set[str]) -> str:
    want = {n.lower() for n in names}
    for node in el.iter():
        if _local(node.tag).lower() in want and node.text and node.text.strip():
            return node.text.strip()
    return ""


def _split_row(line: str) -> list[str]:
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    return [c.strip() for c in re.split(r"\s{2,}", line)]


def parse_table(text: str, allow_no_channel: bool = False) -> ParseResult:
    """Parse Excel paste: camera IP, name, optional target channel (d18).

    Strict mode skips rows without a pure D-number.
    Fill-gap mode (allow_no_channel) keeps those rows with channel_id=0.
    """
    items: list[Assignment] = []
    skipped: list[str] = []
    warnings: list[str] = []
    seen_channels: dict[int, str] = {}
    seen_ips: dict[str, int] = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("监控") or line.startswith("IP") or line.startswith("通道"):
            continue

        cols = [c for c in _split_row(line) if c != ""]
        if not cols:
            continue

        ip = ""
        channel_id: int | None = None
        name_parts: list[str] = []
        skip_note = ""
        for col in cols:
            if IP_RE.fullmatch(col):
                if not ip:
                    ip = col
                continue
            m = CHANNEL_RE.fullmatch(col)
            if m:
                channel_id = int(m.group(1))
                continue
            if any(mark in col for mark in SKIP_CHANNEL_MARKERS):
                skip_note = col
                continue
            name_parts.append(col)

        if not ip:
            skipped.append(f"无 IP，跳过：{line[:80]}")
            continue
        if channel_id is None:
            if allow_no_channel:
                channel_id = 0
                if skip_note:
                    warnings.append(f"{ip} 表中为「{skip_note}」，插空模式将落到下一空位")
            else:
                if skip_note:
                    skipped.append(f"忽略「{skip_note}」，跳过 {ip}")
                else:
                    skipped.append(f"无目标通道，跳过 {ip}")
                continue

        name = " ".join(name_parts).strip()
        if channel_id > 0 and channel_id in seen_channels:
            warnings.append(
                f"目标 D{channel_id} 重复：已有 {seen_channels[channel_id]}，又出现 {ip}"
            )
        if ip in seen_ips:
            prev = seen_ips[ip]
            prev_s = f"D{prev}" if prev > 0 else "插空"
            cur_s = f"D{channel_id}" if channel_id > 0 else "插空"
            warnings.append(f"IP {ip} 重复指定：{prev_s} 与 {cur_s}")
        if channel_id > 0:
            seen_channels[channel_id] = ip
        seen_ips[ip] = channel_id
        items.append(Assignment(ip=ip, name=name, channel_id=channel_id, raw_line=line))

    return ParseResult(items=items, skipped=skipped, warnings=warnings)


def parse_channel_list(xml_text: str) -> dict[int, LiveChannel]:
    root = ET.fromstring(xml_text)
    channels: dict[int, LiveChannel] = {}
    nodes = [root] if _local(root.tag).lower() == "inputproxychannel" else []
    if not nodes:
        nodes = [
            el
            for el in root.iter()
            if _local(el.tag).lower() == "inputproxychannel"
        ]
    for el in nodes:
        cid_text = _find_text(el, {"id"})
        if not cid_text.isdigit():
            continue
        cid = int(cid_text)
        ip = _find_text(el, {"ipaddress", "ipv4address", "hostName", "hostname"})
        name = ""
        for child in list(el):
            if _local(child.tag).lower() == "name" and child.text:
                name = child.text.strip()
                break
        if not name:
            name = _find_text(el, {"name"})
        protocol = _find_text(el, {"proxyprotocol", "protocol"})
        channels[cid] = LiveChannel(
            channel_id=cid, ip=ip, name=name, protocol=protocol
        )
    return channels


def parse_response_status(xml_text: str) -> tuple[str, str]:
    if not xml_text or "<" not in xml_text:
        return "", xml_text.strip()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return "", xml_text.strip()[:300]
    code = _find_text(root, {"statusCode", "statuscode"})
    msg = _find_text(root, {"statusString", "subStatusCode", "statusString"})
    extra = _find_text(root, {"subStatusCode"})
    if extra and extra not in msg:
        msg = f"{msg} {extra}".strip()
    return code, msg or xml_text.strip()[:200]


def is_ok_status(code: str, http_code: int) -> bool:
    if http_code >= 400:
        return False
    if not code:
        return http_code < 400
    return code in {"1", "OK", "ok"}


def looks_already_added(text: str) -> bool:
    t = (text or "").lower()
    return any(m.lower() in t for m in ALREADY_ADDED_MARKERS)


def build_add_xml(
    channel_id: int,
    ip: str,
    name: str,
    opt: NvrOptions,
) -> str:
    nm = xml_escape(name or f"D{channel_id}")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<InputProxyChannel xmlns="http://www.hikvision.com/ver20/XMLSchema" version="2.0">'
        f"<id>{channel_id}</id>"
        f"<name>{nm}</name>"
        "<sourceInputPortDescriptor>"
        f"<proxyProtocol>{xml_escape(opt.protocol)}</proxyProtocol>"
        "<addressingFormatType>ipaddress</addressingFormatType>"
        f"<ipAddress>{xml_escape(ip)}</ipAddress>"
        f"<managePortNo>{opt.cam_port}</managePortNo>"
        f"<srcInputPort>{opt.src_input_port}</srcInputPort>"
        f"<userName>{xml_escape(opt.cam_user)}</userName>"
        f"<password>{xml_escape(opt.cam_password)}</password>"
        "<streamType>auto</streamType>"
        "</sourceInputPortDescriptor>"
        "</InputProxyChannel>"
    )


class NvrClient:
    def __init__(self, opt: NvrOptions):
        self.opt = opt
        self.base_url = opt.base_url.rstrip("/")
        passman = HTTPPasswordMgrWithDefaultRealm()
        passman.add_password(None, self.base_url, opt.nvr_user, opt.nvr_password)
        self.opener = build_opener(
            HTTPDigestAuthHandler(passman),
            HTTPBasicAuthHandler(passman),
        )

    def request(self, method: str, path: str, body: str | None = None) -> tuple[int, str]:
        url = self.base_url + path
        data = body.encode("utf-8") if body is not None else None
        headers = {
            "Accept": "application/xml, text/xml, */*",
            "User-Agent": "HikvisionChannelOrder/1.0",
        }
        if body is not None:
            headers["Content-Type"] = 'application/xml; charset="UTF-8"'
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=self.opt.timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                return getattr(resp, "status", 200) or 200, text
        except HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            return exc.code, text

    def ping(self) -> str:
        code, text = self.request("GET", "/ISAPI/System/deviceInfo")
        if code >= 400:
            raise RuntimeError(f"登录录像机失败 HTTP {code}：{text[:200]}")
        try:
            root = ET.fromstring(text)
            name = _find_text(root, {"deviceName", "model"})
        except ET.ParseError:
            name = ""
        return name or "OK"

    def list_channels(self) -> dict[int, LiveChannel]:
        code, text = self.request("GET", "/ISAPI/ContentMgmt/InputProxy/channels")
        if code >= 400:
            raise RuntimeError(f"读取通道列表失败 HTTP {code}：{text[:200]}")
        return parse_channel_list(text)

    def get_channel(self, channel_id: int) -> LiveChannel | None:
        code, text = self.request(
            "GET", f"/ISAPI/ContentMgmt/InputProxy/channels/{channel_id}"
        )
        if code in {404, 400}:
            return None
        if code >= 400:
            sc, msg = parse_response_status(text)
            if "not exist" in (msg or "").lower() or sc in {"4", "6"}:
                return None
            return None
        try:
            found = parse_channel_list(text)
        except ET.ParseError:
            return None
        return found.get(channel_id) or (next(iter(found.values())) if found else None)

    def delete_channel(self, channel_id: int) -> None:
        code, text = self.request(
            "DELETE", f"/ISAPI/ContentMgmt/InputProxy/channels/{channel_id}"
        )
        sc, msg = parse_response_status(text)
        if is_ok_status(sc, code):
            return
        # already empty
        if code in {404} or "not exist" in (msg or "").lower():
            return
        raise RuntimeError(f"删除 D{channel_id} 失败 HTTP {code} {sc} {msg}".strip())

    def add_channel(self, channel_id: int, ip: str, name: str) -> None:
        xml = build_add_xml(channel_id, ip, name, self.opt)
        last_err = ""
        for attempt in range(1, 4):
            code, text = self.request(
                "POST", "/ISAPI/ContentMgmt/InputProxy/channels", xml
            )
            sc, msg = parse_response_status(text)
            blob = f"{sc} {msg} {text}"
            last_err = f"HTTP {code} {sc} {msg}".strip()
            if looks_already_added(blob):
                err = RuntimeError(f"添加 D{channel_id} 失败 {last_err}")
                err.already_added = True  # type: ignore[attr-defined]
                raise err
            if not is_ok_status(sc, code):
                if attempt < 3:
                    time.sleep(self.opt.settle_seconds)
                    continue
                err = RuntimeError(f"添加 D{channel_id} 失败 {last_err}")
                err.already_added = False  # type: ignore[attr-defined]
                raise err
            channels = self.wait_ip_present(ip)
            placed = channels.get(channel_id)
            if placed and placed.ip == ip:
                return
            landed = self.find_channels_by_ip(ip, channels)
            wrong = [i for i in landed if i != channel_id]
            if not wrong:
                continue
            for fid in wrong:
                self.delete_channel(fid)
            self.wait_ip_absent(ip)
            xml = build_add_xml(channel_id, ip, name, self.opt)
        raise RuntimeError(
            f"添加后 {ip} 未落到 D{channel_id}（最后一次：{last_err}）"
        )

    def add_channel_fill_gap(self, ip: str, name: str, hint_id: int = 0) -> int:
        """Add to the next free slot; accept wherever Hikvision places it."""
        channels = self.list_channels()
        nxt = first_free_channel(set(channels), self.opt.digital_start)
        use_id = hint_id if hint_id > 0 else nxt
        xml = build_add_xml(use_id, ip, name, self.opt)
        last_err = ""
        for attempt in range(1, 4):
            code, text = self.request(
                "POST", "/ISAPI/ContentMgmt/InputProxy/channels", xml
            )
            sc, msg = parse_response_status(text)
            blob = f"{sc} {msg} {text}"
            last_err = f"HTTP {code} {sc} {msg}".strip()
            if looks_already_added(blob):
                err = RuntimeError(f"插空添加失败 {last_err}")
                err.already_added = True  # type: ignore[attr-defined]
                raise err
            if not is_ok_status(sc, code):
                if attempt < 3:
                    time.sleep(self.opt.settle_seconds)
                    continue
                err = RuntimeError(f"插空添加失败 {last_err}")
                err.already_added = False  # type: ignore[attr-defined]
                raise err
            channels = self.wait_ip_present(ip)
            landed = self.find_channels_by_ip(ip, channels)
            if landed:
                return landed[0]
            time.sleep(self.opt.settle_seconds)
        raise RuntimeError(f"插空添加后找不到 {ip}（最后一次：{last_err}）")

    def rename_channel(self, channel_id: int, new_name: str) -> None:
        code, text = self.request(
            "GET", f"/ISAPI/ContentMgmt/InputProxy/channels/{channel_id}"
        )
        if code >= 400:
            raise RuntimeError(f"读取 D{channel_id} 失败 HTTP {code}")
        if not re.search(r"<name>[^<]*</name>", text):
            raise RuntimeError(f"D{channel_id} 响应里找不到 <name>")
        safe = xml_escape(new_name)
        new_xml = re.sub(r"<name>[^<]*</name>", f"<name>{safe}</name>", text, count=1)
        code, text = self.request(
            "PUT",
            f"/ISAPI/ContentMgmt/InputProxy/channels/{channel_id}",
            new_xml,
        )
        sc, msg = parse_response_status(text)
        if not is_ok_status(sc, code):
            raise RuntimeError(f"改名 D{channel_id} 失败 HTTP {code} {sc} {msg}".strip())

    def find_channels_by_ip(
        self, ip: str, channels: dict[int, LiveChannel] | None = None
    ) -> list[int]:
        mapping = channels if channels is not None else self.list_channels()
        return sorted(cid for cid, ch in mapping.items() if ch.ip == ip)

    def wait_ip_absent(self, ip: str, timeout: float | None = None) -> dict[int, LiveChannel]:
        timeout = timeout if timeout is not None else max(8.0, self.opt.settle_seconds * 3)
        time.sleep(self.opt.settle_seconds)
        deadline = time.time() + timeout
        last: dict[int, LiveChannel] = {}
        while True:
            last = self.list_channels()
            if ip not in {ch.ip for ch in last.values()}:
                time.sleep(0.5)
                return last
            if time.time() >= deadline:
                leftover = [f"D{cid}" for cid, ch in last.items() if ch.ip == ip]
                raise RuntimeError(f"等待释放超时，{ip} 仍在 {', '.join(leftover)}")
            time.sleep(1.0)

    def wait_ip_present(self, ip: str, timeout: float | None = None) -> dict[int, LiveChannel]:
        timeout = timeout if timeout is not None else max(8.0, self.opt.settle_seconds * 3)
        deadline = time.time() + timeout
        last: dict[int, LiveChannel] = {}
        while True:
            last = self.list_channels()
            if any(ch.ip == ip for ch in last.values()):
                return last
            if time.time() >= deadline:
                return last
            time.sleep(0.8)


def _channels_holding_ip(
    channels: dict[int, LiveChannel], ip: str, except_id: int | None = None
) -> list[int]:
    return sorted(
        cid
        for cid, ch in channels.items()
        if ch.ip == ip and cid != except_id
    )


def first_free_channel(occupied: set[int], digital_start: int = 1) -> int:
    """海康新增数字通道会落到「从起点起第一个空位」，不是任意指定号。"""
    start = max(1, digital_start)
    n = start
    while n in occupied:
        n += 1
    return n


def sort_assignments(items: list[Assignment]) -> list[Assignment]:
    return sorted(items, key=lambda a: (a.channel_id, a.ip))


def plan_channel_order(
    items: list[Assignment],
    channels: dict[int, LiveChannel],
    digital_start: int = 1,
) -> OrderPlan:
    """按通道号升序模拟增删，找出会因断层而落到错误空位的目标。"""
    ordered = sort_assignments(items)
    occupied = {cid: ch.ip for cid, ch in channels.items()}
    gaps: list[GapIssue] = []
    notes: list[str] = []

    original_order = [a.channel_id for a in items]
    sorted_order = [a.channel_id for a in ordered]
    if original_order != sorted_order:
        notes.append(
            "已按通道号升序重排："
            + " → ".join(f"D{c}" for c in sorted_order)
        )

    for item in ordered:
        cid = item.channel_id
        # 先模拟删掉别处的同一 IP（否则加不进去）
        for oid in [k for k, ip in list(occupied.items()) if ip == item.ip and k != cid]:
            del occupied[oid]
        cur_ip = occupied.get(cid)
        if cur_ip == item.ip:
            continue
        if cur_ip is not None and cur_ip != item.ip:
            del occupied[cid]

        nxt = first_free_channel(set(occupied), digital_start)
        if nxt != cid:
            holes = [
                i
                for i in range(digital_start, cid)
                if i not in occupied
            ]
            detail = (
                f"下一空位是 D{nxt}，目标是 D{cid}。"
                + (
                    f"中间空着：{', '.join(f'D{h}' for h in holes)}。"
                    if holes
                    else ""
                )
                + "海康会按空位顺序落位，不能跳号先加。"
            )
            gaps.append(
                GapIssue(target=cid, next_free=nxt, ip=item.ip, detail=detail)
            )
            # 不假装已占用，后续目标继续对照真实空位
            continue
        occupied[cid] = item.ip

    return OrderPlan(items=ordered, gaps=gaps, notes=notes)


def apply_assignments(
    client: NvrClient,
    items: list[Assignment],
    dry_run: bool,
    on_log: LogFn | None = None,
    should_stop: Callable[[], bool] | None = None,
    fill_gaps: bool = False,
) -> ApplyStats:
    log = on_log or (lambda _m: None)
    stats = ApplyStats()
    log("读取录像机当前数字通道…")
    channels = client.list_channels()
    log(f"当前已配置 {len(channels)} 路数字通道")

    if fill_gaps:
        # 插空：保持粘贴顺序，不强制目标 D，交给海康占下一个空位
        log("模式：插空（有空就加，不强制目标通道号）")
        log(
            "名单顺序："
            + " → ".join(
                (f"D{a.channel_id}" if a.channel_id > 0 else "空位") + f"({a.ip})"
                for a in items
            )
        )
        return _apply_fill_gaps(
            client, items, dry_run, channels, stats, log, should_stop
        )

    plan = plan_channel_order(items, channels, client.opt.digital_start)
    for note in plan.notes:
        log(note)
    if plan.gaps:
        log("发现通道断层（海康按空位顺序落位，跳号会乱）：")
        for g in plan.gaps:
            log(f"  · D{g.target} ← {g.ip}：{g.detail}")
        if not dry_run:
            log("真正写入时会对每一路再核对「下一空位」；对不上的会跳过，避免加错号。")
    items = plan.items
    log(
        "执行顺序（升序）："
        + " → ".join(f"D{a.channel_id}" for a in items)
    )

    for item in items:
        if should_stop and should_stop():
            log("已停止")
            break
        cid = item.channel_id
        current = channels.get(cid)
        others = _channels_holding_ip(channels, item.ip, except_id=cid)
        log("-" * 48)
        log(f"目标 D{cid}  ←  {item.ip}  {item.name or ''}".rstrip())

        if current and current.ip == item.ip:
            if item.name and current.name != item.name:
                log(f"  已在目标通道（现名「{current.name}」）")
                if dry_run:
                    log(f"  [演练] 将改名为「{item.name}」")
                    stats.ok += 1
                else:
                    try:
                        client.rename_channel(cid, item.name)
                        log("  已改名")
                        current.name = item.name
                        stats.ok += 1
                    except Exception as exc:  # noqa: BLE001
                        log(f"  改名失败：{exc}")
                        stats.fail += 1
                        stats.errors.append(str(exc))
            else:
                log("  已在目标通道，跳过")
                stats.skip += 1
            continue

        occupant = f"{current.ip}（{current.name}）" if current else "空"
        log(f"  当前占用：{occupant}")
        if others:
            log(
                "  这台监控还在："
                + "、".join(f"D{i}" for i in others)
            )

        # 模拟删完本机别处占用 / 目标错误占用后，下一空位必须等于目标
        sim_occ = {k for k in channels}
        for oid in others:
            sim_occ.discard(oid)
        if current and current.ip != item.ip:
            sim_occ.discard(cid)
        nxt = first_free_channel(sim_occ, client.opt.digital_start)
        if nxt != cid:
            msg = (
                f"断层：下一空位是 D{nxt}，不能直接加到 D{cid}。"
                f"请先把 D{nxt}～D{cid - 1} 补齐（或纳入本次名单并升序处理）。"
            )
            log(f"  {msg}")
            if dry_run:
                stats.fail += 1
                stats.errors.append(f"D{cid} {item.ip}: {msg}")
                continue
            stats.fail += 1
            stats.errors.append(f"D{cid} {item.ip}: {msg}")
            continue

        if dry_run:
            if others:
                log(
                    "  [演练] 先删除 "
                    + "、".join(f"D{i}" for i in others)
                    + f"，等待约 {client.opt.settle_seconds:.0f} 秒后再添加到 D{cid}"
                )
            if current and current.ip != item.ip:
                log(f"  [演练] 先删除占用通道 D{cid}（{current.ip}）再添加")
            elif not others:
                log(f"  [演练] 下一空位核对 OK（D{nxt}），将直接添加")
            else:
                log(f"  [演练] 下一空位核对 OK（D{nxt}）")
            stats.ok += 1
            # 演练也推进本地占用，方便后续断层判断
            for oid in others:
                channels.pop(oid, None)
            if current and current.ip != item.ip:
                channels.pop(cid, None)
            channels[cid] = LiveChannel(
                channel_id=cid, ip=item.ip, name=item.name or f"D{cid}"
            )
            continue

        try:
            if others:
                for old_id in others:
                    old = channels.get(old_id)
                    log(
                        f"  先删除已存在通道 D{old_id}"
                        + (f"（{old.ip}）" if old else "")
                    )
                    client.delete_channel(old_id)
                    channels.pop(old_id, None)
                log(f"  等待录像机释放 {item.ip}（{client.opt.settle_seconds:.0f}s+）…")
                channels = client.wait_ip_absent(item.ip)

            if current and current.ip != item.ip:
                log(f"  删除占用通道 D{cid}（{current.ip}）")
                client.delete_channel(cid)
                channels.pop(cid, None)
                time.sleep(client.opt.settle_seconds)

            # 删完再核对一次空位，防止中间又变了
            channels = client.list_channels()
            nxt2 = first_free_channel(set(channels), client.opt.digital_start)
            if nxt2 != cid:
                raise RuntimeError(
                    f"删除后下一空位变成 D{nxt2}，不是目标 D{cid}，已中止本条以免加错"
                )
            log(f"  空位核对 OK：下一空位 D{nxt2}")

            try:
                log("  添加…")
                client.add_channel(cid, item.ip, item.name)
            except Exception as exc:  # noqa: BLE001
                already = bool(getattr(exc, "already_added", False)) or looks_already_added(
                    str(exc)
                )
                if not already:
                    raise
                log(f"  添加失败（监控可能尚未释放）：{exc}")
                live = client.list_channels()
                leftover = _channels_holding_ip(live, item.ip, except_id=cid)
                if leftover:
                    for old_id in leftover:
                        old = live.get(old_id)
                        log(
                            f"  删除残留通道 D{old_id}"
                            + (f"（{old.ip}）" if old else "")
                        )
                        client.delete_channel(old_id)
                    log("  再等录像机释放…")
                    client.wait_ip_absent(item.ip)
                else:
                    log("  列表已无该 IP，多等一会再加…")
                    time.sleep(client.opt.settle_seconds)
                channels = client.list_channels()
                nxt3 = first_free_channel(set(channels), client.opt.digital_start)
                if nxt3 != cid:
                    raise RuntimeError(
                        f"重试前下一空位是 D{nxt3}，不是 D{cid}，已中止"
                    )
                log("  再次添加…")
                client.add_channel(cid, item.ip, item.name)

            channels = client.list_channels()
            placed = channels.get(cid)
            if placed and placed.ip == item.ip:
                log(f"  成功：D{cid} ← {item.ip}")
                stats.ok += 1
            else:
                landed = _channels_holding_ip(channels, item.ip)
                raise RuntimeError(
                    "添加完成但核对目标通道失败"
                    + (f"（实际在 {', '.join(f'D{i}' for i in landed)}）" if landed else "")
                )
        except Exception as exc:  # noqa: BLE001
            log(f"  失败：{exc}")
            stats.fail += 1
            stats.errors.append(f"D{cid} {item.ip}: {exc}")
            try:
                channels = client.list_channels()
            except Exception:
                pass
        time.sleep(0.8)

    log("=" * 48)
    log(f"完成：成功/演练 {stats.ok}，跳过 {stats.skip}，失败 {stats.fail}")
    return stats


def _apply_fill_gaps(
    client: NvrClient,
    items: list[Assignment],
    dry_run: bool,
    channels: dict[int, LiveChannel],
    stats: ApplyStats,
    log: LogFn,
    should_stop: Callable[[], bool] | None,
) -> ApplyStats:
    """Insert into next free slots; Hikvision chooses the channel number."""
    for item in items:
        if should_stop and should_stop():
            log("已停止")
            break

        existing = _channels_holding_ip(channels, item.ip)
        hint = f"表中 D{item.channel_id}" if item.channel_id > 0 else "表中无通道号"
        log("-" * 48)
        log(f"插空  ←  {item.ip}  {item.name or ''}（{hint}）".rstrip())

        if existing:
            where = "、".join(f"D{i}" for i in existing)
            if item.name:
                ch0 = channels.get(existing[0])
                if ch0 and ch0.name != item.name:
                    log(f"  已在 {where}，将改名")
                    if dry_run:
                        log(f"  [演练] 改名为「{item.name}」")
                        stats.ok += 1
                    else:
                        try:
                            client.rename_channel(existing[0], item.name)
                            channels[existing[0]].name = item.name
                            log(f"  已改名（仍在 {where}）")
                            stats.ok += 1
                        except Exception as exc:  # noqa: BLE001
                            log(f"  改名失败：{exc}")
                            stats.fail += 1
                            stats.errors.append(str(exc))
                    continue
            log(f"  已在 {where}，跳过")
            stats.skip += 1
            continue

        nxt = first_free_channel(set(channels), client.opt.digital_start)
        log(f"  预测下一空位：D{nxt}")

        if dry_run:
            log(f"  [演练] 将添加到下一空位 D{nxt}（由海康落位）")
            channels[nxt] = LiveChannel(
                channel_id=nxt, ip=item.ip, name=item.name or f"D{nxt}"
            )
            stats.ok += 1
            continue

        try:
            log("  添加…")
            try:
                landed = client.add_channel_fill_gap(
                    item.ip, item.name, hint_id=nxt
                )
            except Exception as exc:  # noqa: BLE001
                already = bool(getattr(exc, "already_added", False)) or looks_already_added(
                    str(exc)
                )
                if not already:
                    raise
                log(f"  报已存在，刷新列表…：{exc}")
                live = client.list_channels()
                leftover = _channels_holding_ip(live, item.ip)
                if leftover:
                    for old_id in leftover:
                        log(f"  删除残留 D{old_id}")
                        client.delete_channel(old_id)
                    client.wait_ip_absent(item.ip)
                else:
                    time.sleep(client.opt.settle_seconds)
                log("  再次插空添加…")
                landed = client.add_channel_fill_gap(item.ip, item.name, hint_id=0)

            channels = client.list_channels()
            placed = channels.get(landed)
            if placed and placed.ip == item.ip:
                note = ""
                if item.channel_id > 0 and item.channel_id != landed:
                    note = f"（表中写 D{item.channel_id}，实际 D{landed}）"
                log(f"  成功：D{landed} ← {item.ip}{note}")
                stats.ok += 1
            else:
                raise RuntimeError("插空添加后核对失败")
        except Exception as exc:  # noqa: BLE001
            log(f"  失败：{exc}")
            stats.fail += 1
            stats.errors.append(f"{item.ip}: {exc}")
            try:
                channels = client.list_channels()
            except Exception:
                pass
        time.sleep(0.8)

    log("=" * 48)
    log(f"完成：成功/演练 {stats.ok}，跳过 {stats.skip}，失败 {stats.fail}")
    return stats


# AIGC END
