"""Builds the workbook's VBA project (vbaProject.bin) straight from macros.bas.

Normally you have to make an .xlsm in Excel and extract this file by hand.
Instead we write it ourselves following Microsoft's published format
([MS-OVBA] for the VBA parts, [MS-CFB] for the container). The project is
written as "source only" (_VBA_PROJECT version 0xFFFF), which tells Excel to
compile the macros itself the first time the file is opened - so it works on
32-bit and 64-bit Office alike. Nothing here runs any code."""
import os
import struct
import uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
ENDOFCHAIN, FREESECT, FATSECT, NOSTREAM = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFF

WORKBOOK_ATTRS = ('Attribute VB_Name = "{name}"\r\nAttribute VB_Base = "0{{00020819-0000-0000-C000-000000000046}}"\r\n'
                  'Attribute VB_GlobalNameSpace = False\r\nAttribute VB_Creatable = False\r\n'
                  'Attribute VB_PredeclaredId = True\r\nAttribute VB_Exposed = True\r\n'
                  'Attribute VB_TemplateDerived = False\r\nAttribute VB_Customizable = True\r\n')
SHEET_ATTRS = ('Attribute VB_Name = "{name}"\r\nAttribute VB_Base = "0{{00020820-0000-0000-C000-000000000046}}"\r\n'
               'Attribute VB_GlobalNameSpace = False\r\nAttribute VB_Creatable = False\r\n'
               'Attribute VB_PredeclaredId = True\r\nAttribute VB_Exposed = True\r\n'
               'Attribute VB_TemplateDerived = False\r\nAttribute VB_Customizable = True\r\n')


# ------------------------------------------------------------------ MS-OVBA compression (2.4.1)
def _copy_token_help(diff):
    bit_count = 4
    while (1 << bit_count) < diff:
        bit_count += 1
    length_mask = 0xFFFF >> bit_count
    offset_mask = (~length_mask) & 0xFFFF
    maximum_length = length_mask + 3
    return length_mask, offset_mask, bit_count, maximum_length


def _compress_chunk(chunk):
    out = bytearray()
    pos = 0
    n = len(chunk)
    while pos < n:
        flag_at = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if pos >= n:
                break
            _, _, bit_count, max_len = _copy_token_help(pos)
            best_len, best_off = 0, 0
            if pos > 0:
                limit = min(max_len, n - pos)
                for cand in range(pos - 1, -1, -1):
                    ln = 0
                    while ln < limit and chunk[cand + ln] == chunk[pos + ln]:
                        ln += 1
                    if ln > best_len:
                        best_len, best_off = ln, pos - cand
                        if ln == limit:
                            break
            if best_len >= 3:
                token = ((best_off - 1) << (16 - bit_count)) | (best_len - 3)
                out += struct.pack("<H", token)
                flags |= 1 << bit
                pos += best_len
            else:
                out.append(chunk[pos])
                pos += 1
        out[flag_at] = flags
    return bytes(out)


def compress(data):
    out = bytearray(b"\x01")
    for i in range(0, len(data), 4096):
        chunk = data[i:i + 4096]
        comp = _compress_chunk(chunk)
        if len(comp) > 4096 and len(chunk) == 4096:
            out += struct.pack("<H", 0x3000 | 0x0FFF) + chunk          # raw chunk
        else:
            if len(comp) > 4096:
                raise ValueError("VBA text could not be compressed (it is never random data, so this means a bug)")
            out += struct.pack("<H", 0xB000 | (len(comp) + 2 - 3)) + comp
    return bytes(out)


def decompress(data):
    """Only used by the tests to prove compress() is right."""
    assert data[0] == 1
    out = bytearray()
    pos = 1
    while pos < len(data):
        header = struct.unpack("<H", data[pos:pos + 2])[0]
        size = (header & 0x0FFF) + 3
        compressed = header & 0x8000
        chunk_end = pos + size
        pos += 2
        start = len(out)
        if not compressed:
            out += data[pos:pos + 4096]
            pos += 4096
            continue
        while pos < chunk_end:
            flags = data[pos]
            pos += 1
            for bit in range(8):
                if pos >= chunk_end:
                    break
                if flags & (1 << bit):
                    token = struct.unpack("<H", data[pos:pos + 2])[0]
                    pos += 2
                    length_mask, offset_mask, bit_count, _ = _copy_token_help(len(out) - start)
                    length = (token & length_mask) + 3
                    offset = ((token & offset_mask) >> (16 - bit_count)) + 1
                    for _ in range(length):
                        out.append(out[-offset])
                else:
                    out.append(data[pos])
                    pos += 1
    return bytes(out)


# ------------------------------------------------------------------ dir stream (2.3.4.2)
def _rec(rid, payload):
    return struct.pack("<HI", rid, len(payload)) + payload


def _dir_stream(modules, codepage=1252):
    enc = "cp1252"
    b = bytearray()
    b += _rec(0x0001, struct.pack("<I", 1))                       # SYSKIND win32
    b += _rec(0x0002, struct.pack("<I", 0x0409))                  # LCID
    b += _rec(0x0014, struct.pack("<I", 0x0409))                  # LCIDINVOKE
    b += _rec(0x0003, struct.pack("<H", codepage))                # CODEPAGE
    b += _rec(0x0004, b"VBAProject")                              # NAME
    b += _rec(0x0005, b"") + _rec(0x0040, b"")                    # DOCSTRING
    b += _rec(0x0006, b"") + _rec(0x003D, b"")                    # HELPFILEPATH
    b += _rec(0x0007, struct.pack("<I", 0))                       # HELPCONTEXT
    b += _rec(0x0008, struct.pack("<I", 0))                       # LIBFLAGS
    b += struct.pack("<HIIH", 0x0009, 4, 1, 0)                    # VERSION (size field is 4, then 6 bytes)
    b += _rec(0x000C, b"") + _rec(0x003C, b"")                    # CONSTANTS
    # reference to stdole (OLE Automation)
    name = b"stdole"
    b += _rec(0x0016, name) + _rec(0x003E, "stdole".encode("utf-16-le"))
    libid = b"*\\G{00020430-0000-0000-C000-000000000046}#2.0#0#C:\\Windows\\System32\\stdole2.tlb#OLE Automation"
    b += _rec(0x000D, struct.pack("<I", len(libid)) + libid + struct.pack("<IH", 0, 0))
    b += _rec(0x000F, struct.pack("<H", len(modules)))            # MODULES count
    b += _rec(0x0013, struct.pack("<H", 0xFFFF))                  # COOKIE
    for m in modules:
        nm = m["name"].encode(enc)
        nu = m["name"].encode("utf-16-le")
        b += _rec(0x0019, nm)
        b += _rec(0x0047, nu)
        b += _rec(0x001A, nm) + _rec(0x0032, nu)
        b += _rec(0x001C, b"") + _rec(0x0048, b"")
        b += _rec(0x0031, struct.pack("<I", 0))                   # text offset 0 (source only)
        b += _rec(0x001E, struct.pack("<I", 0))
        b += _rec(0x002C, struct.pack("<H", 0xFFFF))
        b += _rec(0x0021 if m["type"] == "std" else 0x0022, b"")
        b += _rec(0x002B, b"")                                     # module terminator
    b += _rec(0x0010, b"")                                         # dir terminator
    return bytes(b)


# ------------------------------------------------------------------ PROJECT stream protection fields (2.4.3)
def _encrypt(project_id, data, seed=0x5A):
    version = 2
    proj_key = sum(project_id.encode("cp1252")) & 0xFF
    out = bytearray([seed, seed ^ version, seed ^ proj_key])
    unencrypted_1 = proj_key
    encrypted_1 = out[2]
    encrypted_2 = out[1]
    ignored_len = (seed & 6) // 2
    for _ in range(ignored_len):
        temp = 7
        byte_enc = temp ^ ((encrypted_2 + unencrypted_1) & 0xFF)
        out.append(byte_enc)
        encrypted_2, encrypted_1, unencrypted_1 = encrypted_1, byte_enc, temp
    for byte in struct.pack("<I", len(data)) + data:
        byte_enc = byte ^ ((encrypted_2 + unencrypted_1) & 0xFF)
        out.append(byte_enc)
        encrypted_2, encrypted_1, unencrypted_1 = encrypted_1, byte_enc, byte
    return "".join(f"{x:02X}" for x in out)


def _project_stream(modules, project_id):
    lines = [f'ID="{project_id}"']
    for m in modules:
        if m["type"] == "doc":
            lines.append(f"Document={m['name']}/&H00000000")
    for m in modules:
        if m["type"] == "std":
            lines.append(f"Module={m['name']}")
    lines += ['Name="VBAProject"', 'HelpContextID="0"', 'VersionCompatible32="393222000"',
              f'CMG="{_encrypt(project_id, struct.pack("<I", 0), 0x3A)}"',
              f'DPB="{_encrypt(project_id, bytes([0]), 0x4C)}"',
              f'GC="{_encrypt(project_id, bytes([0xFF]), 0x6E)}"',
              "", "[Host Extender Info]", "&H00000001={3832D640-CF90-11CF-8E43-00A0C911005A};VBE;&H00000000", "", ""]
    return "\r\n".join(lines).encode("cp1252")


def _projectwm(modules):
    b = bytearray()
    for m in modules:
        b += m["name"].encode("cp1252") + b"\x00" + m["name"].encode("utf-16-le") + b"\x00\x00"
    b += b"\x00\x00"
    return bytes(b)


# ------------------------------------------------------------------ MS-CFB writer
class _Entry:
    def __init__(self, name, kind, data=b"", children=None):
        self.name, self.kind, self.data = name, kind, data
        self.children = children or []
        self.sid = None
        self.left = self.right = self.child = NOSTREAM
        self.color = 1
        self.start = ENDOFCHAIN
        self.size = 0


def _cfb_key(e):
    return (len(e.name), e.name.upper())


def _build_tree(entries, depth=0, info=None):
    """Balanced binary search tree of siblings, coloured as a valid red-black tree."""
    if not entries:
        return NOSTREAM, -1
    mid = len(entries) // 2
    node = entries[mid]
    lroot, ld = _build_tree(entries[:mid], depth + 1, info)
    rroot, rd = _build_tree(entries[mid + 1:], depth + 1, info)
    node.left, node.right = lroot, rroot
    node._depth = depth
    return node.sid, max(depth, ld, rd)


def _color_tree(entries):
    if not entries:
        return
    _, maxd = _build_tree(entries)
    n = len(entries)
    perfect = (n + 1) & n == 0
    for e in entries:
        e.color = 0 if (not perfect and e._depth == maxd) else 1


def cfb(root_children):
    """root_children: list of _Entry (streams or storages). Returns the compound file bytes."""
    SECTOR, MINI, CUTOFF = 512, 64, 4096
    root = _Entry("Root Entry", 5, children=root_children)
    order = []

    def walk(e):
        e.sid = len(order)
        order.append(e)
        for c in sorted(e.children, key=_cfb_key):
            walk(c)
    walk(root)
    for e in order:
        if e.children:
            kids = sorted(e.children, key=_cfb_key)
            _color_tree(kids)
            e.child, _ = _build_tree(kids)
            _color_tree(kids)
    root.color = 1
    # mini stream
    mini = bytearray()
    minifat = []
    big = []
    for e in order:
        if e.kind != 2:
            continue
        e.size = len(e.data)
        if e.size == 0:
            e.start = ENDOFCHAIN
            continue
        if e.size < CUTOFF:
            start = len(mini) // MINI
            nsec = (e.size + MINI - 1) // MINI
            mini += e.data + b"\x00" * (nsec * MINI - e.size)
            for i in range(nsec):
                minifat.append(start + i + 1 if i < nsec - 1 else ENDOFCHAIN)
            e.start = start
        else:
            big.append(e)
    n_dir = (len(order) * 128 + SECTOR - 1) // SECTOR
    n_minifat = (len(minifat) * 4 + SECTOR - 1) // SECTOR
    n_ministream = (len(mini) + SECTOR - 1) // SECTOR
    n_big = sum((len(e.data) + SECTOR - 1) // SECTOR for e in big)
    n_fat = 1
    while True:
        total = n_fat + n_minifat + n_dir + n_ministream + n_big
        if (n_fat * SECTOR // 4) >= total:
            break
        n_fat += 1
    fat = []
    sec = 0
    fat_secs = list(range(sec, sec + n_fat))
    fat += [FATSECT] * n_fat
    sec += n_fat

    def chain(n):
        nonlocal sec
        s0 = sec
        for i in range(n):
            fat.append(sec + 1 if i < n - 1 else ENDOFCHAIN)
            sec += 1
        return s0 if n else ENDOFCHAIN
    minifat_start = chain(n_minifat)
    dir_start = chain(n_dir)
    ministream_start = chain(n_ministream)
    for e in big:
        e.start = chain((len(e.data) + SECTOR - 1) // SECTOR)
    root.start = ministream_start if mini else ENDOFCHAIN
    root.size = len(mini)
    fat += [FREESECT] * (n_fat * SECTOR // 4 - len(fat))
    # header
    difat = fat_secs + [FREESECT] * (109 - len(fat_secs))
    header = bytearray()
    header += bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 16
    header += struct.pack("<HHHHH", 0x003E, 0x0003, 0xFFFE, 9, 6) + b"\x00" * 6
    header += struct.pack("<IIIIIIIII", 0, n_fat, dir_start, 0, CUTOFF,
                          minifat_start if n_minifat else ENDOFCHAIN, n_minifat, ENDOFCHAIN, 0)
    header += struct.pack("<109I", *difat)
    assert len(header) == 512
    body = bytearray()
    body += struct.pack(f"<{len(fat)}I", *fat)
    mf = minifat + [FREESECT] * (n_minifat * SECTOR // 4 - len(minifat))
    body += struct.pack(f"<{len(mf)}I", *mf)
    d = bytearray()
    for e in order:
        nm = e.name.encode("utf-16-le")
        d += nm + b"\x00" * (64 - len(nm))
        d += struct.pack("<HBB", len(nm) + 2, e.kind, e.color)
        d += struct.pack("<III", e.left, e.right, e.child)
        d += b"\x00" * 16 + struct.pack("<I", 0) + b"\x00" * 16
        d += struct.pack("<IIi", e.start if (e.kind == 2 or e.kind == 5) else 0, e.size if e.kind != 1 else 0, 0)
    while len(d) < n_dir * SECTOR:
        d += b"\x00" * 64 + struct.pack("<HBB", 0, 0, 0) + struct.pack("<III", NOSTREAM, NOSTREAM, NOSTREAM) + \
             b"\x00" * 36 + struct.pack("<IIi", 0, 0, 0)
    body += d
    body += mini + b"\x00" * (n_ministream * SECTOR - len(mini))
    for e in big:
        nsec = (len(e.data) + SECTOR - 1) // SECTOR
        body += e.data + b"\x00" * (nsec * SECTOR - len(e.data))
    return bytes(header + body)


# ------------------------------------------------------------------ public
def module_source():
    with open(os.path.join(_HERE, "macros.bas"), encoding="utf-8") as fh:
        text = fh.read()
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def build_vba_project(sheet_codenames, std_modules=None):
    """sheet_codenames: e.g. ['Sheet1', 'Sheet2', ...] (one per worksheet, in order)."""
    std_modules = std_modules or [("RDPSMacros", module_source())]
    modules = [{"name": "ThisWorkbook", "type": "doc", "code": WORKBOOK_ATTRS.format(name="ThisWorkbook")}]
    for nm in sheet_codenames:
        modules.append({"name": nm, "type": "doc", "code": SHEET_ATTRS.format(name=nm)})
    for nm, code in std_modules:
        modules.append({"name": nm, "type": "std", "code": code})
    project_id = "{" + str(uuid.UUID(int=0x5244505300000000000000004D534D53)).upper() + "}"
    vba_children = [_Entry("dir", 2, compress(_dir_stream(modules))),
                    _Entry("_VBA_PROJECT", 2, bytes([0xCC, 0x61, 0xFF, 0xFF, 0x00, 0x00, 0x00]))]
    for m in modules:
        vba_children.append(_Entry(m["name"], 2, compress(m["code"].encode("cp1252"))))
    root_children = [_Entry("VBA", 1, children=vba_children),
                     _Entry("PROJECT", 2, _project_stream(modules, project_id)),
                     _Entry("PROJECTwm", 2, _projectwm(modules))]
    return cfb(root_children)
