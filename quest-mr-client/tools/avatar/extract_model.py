"""解压 MMD 模型包，并修正非 UTF-8 文件名（GBK / Shift-JIS）。

为什么不用 Expand-Archive：zip 里存的是 GBK/Shift-JIS 字节，
Windows 解压后中文会变乱码，PMX 里引用的贴图路径就对不上，模型导入后没贴图。

用法：
    python extract_model.py <zip> <out_dir>
"""
import os
import struct
import sys
import zipfile


def decode_name(raw: bytes) -> str:
    """在 GBK / Shift-JIS / cp437 中挑一个最不“别扭”的编码。"""
    candidates = []
    for enc in ("utf-8", "gbk", "shift_jis", "cp437"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        bad = text.count("\ufffd")
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff"
                  or "\u3040" <= ch <= "\u30ff")
        candidates.append((bad, -cjk, enc, text))
    if not candidates:
        return raw.decode("utf-8", errors="replace")
    candidates.sort()
    return candidates[0][3]


def read_central_directory(path: str):
    """手工解析中央目录，拿到文件名的原始字节。"""
    with open(path, "rb") as fh:
        data = fh.read()
    eocd = data.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise ValueError("不是有效的 zip")
    total = struct.unpack_from("<H", data, eocd + 10)[0]
    offset = struct.unpack_from("<I", data, eocd + 16)[0]
    entries = []
    for _ in range(total):
        if data[offset:offset + 4] != b"PK\x01\x02":
            break
        name_len = struct.unpack_from("<H", data, offset + 28)[0]
        extra_len = struct.unpack_from("<H", data, offset + 30)[0]
        comment_len = struct.unpack_from("<H", data, offset + 32)[0]
        external = struct.unpack_from("<I", data, offset + 38)[0]
        local_off = struct.unpack_from("<I", data, offset + 42)[0]
        raw_name = data[offset + 46:offset + 46 + name_len]
        entries.append((raw_name, local_off, external))
        offset += 46 + name_len + extra_len + comment_len
    return entries


def read_pmx_textures(pmx_path: str):
    """解析 PMX 的贴图表，用于校验解压后的贴图名是否对得上。"""
    with open(pmx_path, "rb") as fh:
        blob = fh.read()
    if blob[:4] != b"PMX ":
        return None
    pos = 4
    pos += 4  # version
    header_size = blob[pos]
    pos += 1
    flags = blob[pos:pos + header_size]
    pos += header_size
    # PMX 全局标志顺序：encoding, additionalUV, vertexIndexSize, textureIndexSize, ...
    encoding = flags[0]

    def read_text() -> str:
        nonlocal pos
        length = struct.unpack_from("<i", blob, pos)[0]
        pos += 4
        raw = blob[pos:pos + length]
        pos += length
        if encoding == 0:
            return raw.decode("utf-16-le", errors="replace")
        return raw.decode("utf-8", errors="replace")

    vertex_index_size = flags[2]
    texture_index_size = flags[3]
    read_text()  # name
    read_text()  # name_en
    read_text()  # comment
    read_text()  # comment_en

    vertex_count = struct.unpack_from("<i", blob, pos)[0]
    pos += 4
    for _ in range(vertex_count):
        pos += 4 * 8  # pos + normal + uv
        additional = flags[1]
        if additional:
            pos += 4 * 4 * additional
        weight_type = blob[pos]
        pos += 1
        if weight_type == 0:
            pos += vertex_index_size
        elif weight_type == 1:
            # BDEF2: 2 个骨骼索引 + 1 个权重
            pos += vertex_index_size * 2 + 4
        elif weight_type == 2:
            pos += vertex_index_size * 4
        elif weight_type == 3:
            # SDEF: 2 个骨骼索引 + C/R0/R1 三个向量（9 个 float）
            pos += vertex_index_size * 2 + 4 * 9
        elif weight_type == 4:
            pos += vertex_index_size * 4 + 4 * 4
        pos += 4  # edge scale

    face_count = struct.unpack_from("<i", blob, pos)[0]
    pos += 4 + face_count * vertex_index_size
    texture_count = struct.unpack_from("<i", blob, pos)[0]
    pos += 4
    return [read_text() for _ in range(texture_count)]


def main() -> int:
    zip_path, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    entries = read_central_directory(zip_path)
    names = {}
    with zipfile.ZipFile(zip_path) as zf:
        for raw_name, local_off, external in entries:
            name = decode_name(raw_name).replace("\\", "/")
            if name.endswith("/"):
                continue
            info = None
            for candidate in zf.infolist():
                if candidate.header_offset == local_off:
                    info = candidate
                    break
            if info is None:
                continue
            target = os.path.join(out_dir, *[p for p in name.split("/") if p])
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            names[name] = target
            print("解压:", name.encode("unicode_escape").decode("ascii"))

    pmx_files = [p for p in names.values() if p.lower().endswith(".pmx")]
    if not pmx_files:
        print("!! 没有找到 .pmx")
        return 1
    main_pmx = max(pmx_files, key=os.path.getsize)
    textures = read_pmx_textures(main_pmx)
    print("\n主模型:", os.path.basename(main_pmx),
          f"({os.path.getsize(main_pmx) / 1024 / 1024:.1f} MB)")
    if textures is None:
        print("PMX 解析失败")
        return 1
    print("PMX 引用贴图数:", len(textures))
    missing = []
    for tex in textures:
        rel = tex.replace("\\", "/")
        if not rel:
            continue
        candidate = os.path.join(out_dir, *rel.split("/"))
        if not os.path.exists(candidate):
            missing.append(tex)
    if missing:
        print("缺失贴图", len(missing), "个：")
        for m in missing[:20]:
            print("   -", m)
    else:
        print("贴图校验: 全部存在 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
