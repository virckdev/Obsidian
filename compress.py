#!/usr/bin/env python3
import os
import sys
import lz4.block
import base64

EXCLUDED_DIRS = {"Compressed", ".vscode", ".git"}
EXCLUDED_FILES = {"compress.py", "README.md"}

OLD_URL = "https://raw.githubusercontent.com/white558/Obsidian/main/"
NEW_URL = "https://raw.githubusercontent.com/white558/Obsidian/main/Compressed/"

TEXT_EXTENSIONS = {".lua"}
LUA_EXTENSIONS = {".lua", ".luau"}
IMG_EXTENSIONS = {".png"}

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
COMPRESSED_DIR = os.path.join(ROOT_DIR, "Compressed")

LUA_DECOMPRESSOR = '''local function d(c)local t={}local i=5 local n=#c while i<=n do local b=string.byte local o=b(c,i)i=i+1 local l=math.floor(o/16)if l>=15 then repeat local x=b(c,i)i=i+1 l=l+x until x~=255 end for j=1,l do t[#t+1]=b(c,i)i=i+1 end if i>n then break end local f=b(c,i)+b(c,i+1)*256 i=i+2 local m=o%16+4 if m>=19 then repeat local x=b(c,i)i=i+1 m=m+x until x~=255 end local p=#t for j=1,m do t[p+j]=t[p-f+j]end end local r={}for i=1,#t,4096 do local c={}for j=i,math.min(i+4095,#t)do c[j-i+1]=string.char(t[j])end r[#r+1]=table.concat(c)end return table.concat(r)end local s="__BASE64_PAYLOAD__" loadstring(d(crypt.base64decode(s)))()'''

T_COMMENT = "COMMENT"
T_STRING = "STRING"
T_NUMBER = "NUMBER"
T_IDENT = "IDENT"
T_OP = "OP"
T_EOF = "EOF"

KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for",
    "function", "if", "in", "local", "nil", "not", "or", "repeat",
    "return", "then", "true", "until", "while",
    "continue", "export", "type",
}

LUAU_OPERATORS = [
    "...", ">>>", "..=",
    "..", "::", "->", "==", "~=", "<=", ">=", "//",
    "+=", "-=", "*=", "/=", "%=", "^=", "<<", ">>",
    "&=", "|=", "^=",
    "+", "-", "*", "/", "%", "^", "#", "&", "|", "~",
    "=", "<", ">", "(", ")", "{", "}", "[", "]",
    ";", ":", ",", ".", "?",
]


class Token:
    __slots__ = ("type", "value")

    def __init__(self, type_, value):
        self.type = type_
        self.value = value

    def __repr__(self):
        return f"Token({self.type}, {self.value!r})"


def tokenize(src):
    tokens = []
    i = 0
    n = len(src)

    while i < n:
        c = src[i]

        if c in " \t\r\n\f\v":
            i += 1
            continue

        if c == "-" and i + 1 < n and src[i + 1] == "-":
            if i + 2 < n and src[i + 2] == "[":
                eq_count, j = _match_long_bracket_open(src, i + 2)
                if j is not None:
                    close = "]" + ("=" * eq_count) + "]"
                    end = src.find(close, j)
                    if end == -1:
                        tokens.append(Token(T_COMMENT, src[i:]))
                        i = n
                    else:
                        tokens.append(Token(T_COMMENT, src[i:end + len(close)]))
                        i = end + len(close)
                    continue
            j = i
            while j < n and src[j] != "\n":
                j += 1
            tokens.append(Token(T_COMMENT, src[i:j]))
            i = j
            continue

        if c == '"' or c == "'":
            j = _read_short_string(src, i, n)
            tokens.append(Token(T_STRING, src[i:j]))
            i = j
            continue

        if c == "`":
            j = i + 1
            while j < n:
                cc = src[j]
                if cc == "\\" and j + 1 < n:
                    j += 2
                    continue
                if cc == "`":
                    j += 1
                    break
                if cc == "{":
                    depth = 1
                    j += 1
                    while j < n and depth > 0:
                        if src[j] == "{" and (j == 0 or src[j-1] != "\\"):
                            depth += 1
                        elif src[j] == "}" and (j == 0 or src[j-1] != "\\"):
                            depth -= 1
                        j += 1
                    continue
                j += 1
            tokens.append(Token(T_STRING, src[i:j]))
            i = j
            continue

        if c == "[":
            eq_count, j = _match_long_bracket_open(src, i)
            if j is not None:
                close = "]" + ("=" * eq_count) + "]"
                end = src.find(close, j)
                if end == -1:
                    tokens.append(Token(T_STRING, src[i:]))
                    i = n
                else:
                    tokens.append(Token(T_STRING, src[i:end + len(close)]))
                    i = end + len(close)
                continue

        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            j = _read_number(src, i, n)
            tokens.append(Token(T_NUMBER, src[i:j]))
            i = j
            continue

        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            tokens.append(Token(T_IDENT, src[i:j]))
            i = j
            continue

        matched = False
        for op in LUAU_OPERATORS:
            if src.startswith(op, i):
                tokens.append(Token(T_OP, op))
                i += len(op)
                matched = True
                break
        if not matched:
            tokens.append(Token(T_OP, c))
            i += 1

    tokens.append(Token(T_EOF, ""))
    return tokens


def _match_long_bracket_open(src, i):
    n = len(src)
    if i >= n or src[i] != "[":
        return 0, None
    j = i + 1
    eq_count = 0
    while j < n and src[j] == "=":
        eq_count += 1
        j += 1
    if j < n and src[j] == "[":
        return eq_count, j + 1
    return 0, None


def _read_short_string(src, i, n):
    quote = src[i]
    j = i + 1
    while j < n:
        c = src[j]
        if c == "\\":
            if j + 1 < n and src[j + 1] == "z":
                j += 2
                while j < n and src[j] in " \t\r\n\f\v":
                    j += 1
                continue
            j += 2
            continue
        if c == quote:
            return j + 1
        if c == "\n":
            return j
        j += 1
    return j


def _read_number(src, i, n):
    c = src[i]

    if c == "0" and i + 1 < n and src[i + 1] in "xX":
        j = i + 2
        while j < n and (src[j] in "0123456789abcdefABCDEF._"):
            j += 1
        if j < n and src[j] in "pP":
            j += 1
            if j < n and src[j] in "+-":
                j += 1
            while j < n and (src[j].isdigit() or src[j] == "_"):
                j += 1
        return j

    if c == "0" and i + 1 < n and src[i + 1] in "bB":
        j = i + 2
        while j < n and (src[j] in "01_"):
            j += 1
        return j

    j = i
    while j < n and (src[j].isdigit() or src[j] == "_"):
        j += 1
    if j < n and src[j] == ".":
        j += 1
        while j < n and (src[j].isdigit() or src[j] == "_"):
            j += 1
    if j < n and src[j] in "eE":
        j += 1
        if j < n and src[j] in "+-":
            j += 1
        while j < n and (src[j].isdigit() or src[j] == "_"):
            j += 1
    return j


def _need_space(left, right):
    if left.type == T_EOF or right.type == T_EOF:
        return False

    lt, rt = left.type, right.type
    lv, rv = left.value, right.value

    if lt == T_IDENT and rt == T_IDENT:
        return True
    if lt == T_IDENT and rt == T_NUMBER:
        return True
    if lt == T_NUMBER and rt == T_IDENT:
        return True
    if lt == T_NUMBER and rt == T_NUMBER:
        return True
    if lt == T_NUMBER and rt == T_OP and rv[0] == ".":
        return True
    if lt == T_OP and lv == "-" and rt == T_OP and rv == "-":
        return True
    if lt == T_OP and lv == "[" and rt == T_OP and rv and rv[0] == "[":
        return True
    if lt == T_OP and lv == ".." and rt == T_OP and rv == ".":
        return True
    if lt == T_OP and lv == "=" and rt == T_OP and rv == "=":
        return True
    if lt == T_OP and lv == "<" and rt == T_OP and rv == "<":
        return True
    if lt == T_OP and lv == ">" and rt == T_OP and rv == ">":
        return True
    if lt == T_OP and lv == ">" and rt == T_OP and rv == ">=":
        return True
    if lt == T_OP and lv == "/" and rt == T_OP and rv == "/":
        return True
    if lt == T_OP and lv == "/" and rt == T_OP and rv == "//=":
        return True
    if lt == T_OP and lv == "~" and rt == T_OP and rv == "=":
        return True
    if lt == T_OP and lv == ":" and rt == T_OP and rv == ":":
        return True
    if lt == T_OP and lv == "-" and rt == T_OP and rv == ">":
        return True

    return False


def _need_semicolon(left, right):
    if left.type != T_OP or left.value != ";":
        return False
    if right.type == T_EOF:
        return False
    if right.type == T_OP and right.value in ("(", "{"):
        return True
    if right.type == T_STRING:
        return True
    return False


def _normalize_short_string(value):
    if "\\z" not in value:
        return value
    if not value or value[0] not in "\"'":
        return value
    quote = value[0]
    out = [quote]
    i = 1
    n = len(value)
    while i < n - 1:
        c = value[i]
        if c == "\\" and i + 1 < n:
            nxt = value[i + 1]
            if nxt == "z":
                i += 2
                while i < n - 1 and value[i] in " \t\r\n\f\v":
                    i += 1
                continue
            else:
                out.append(value[i:i + 2])
                i += 2
                continue
        out.append(c)
        i += 1
    out.append(quote)
    return "".join(out)


def _long_string_to_short(value):
    if not value.startswith("["):
        return None
    j = 1
    while j < len(value) and value[j] == "=":
        j += 1
    if j >= len(value) or value[j] != "[":
        return None
    eq_count = j - 1
    open_bracket = "[" + ("=" * eq_count) + "["
    close_bracket = "]" + ("=" * eq_count) + "]"
    if not value.startswith(open_bracket) or not value.endswith(close_bracket):
        return None
    if len(value) < len(open_bracket) + len(close_bracket):
        return None

    content = value[len(open_bracket):-len(close_bracket)]

    if content.startswith("\n"):
        content = content[1:]
    elif content.startswith("\r\n"):
        content = content[2:]
    elif content.startswith("\r"):
        content = content[1:]

    has_double = '"' in content
    has_single = "'" in content
    if not has_double:
        quote = '"'
        escaped = content.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace('"', '\\"')
    elif not has_single:
        quote = "'"
        escaped = content.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("'", "\\'")
    else:
        quote = '"'
        escaped = (
            content
            .replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace('"', '\\"')
        )
    return quote + escaped + quote


def _collect_scopes(tokens):
    scopes = []
    declared = set()
    global_reads = set()
    i = 0
    n = len(tokens)

    def push_scope():
        scopes.append({})

    def pop_scope():
        if scopes:
            scopes.pop()

    def declare(name):
        if scopes:
            scopes[-1][name] = True
        declared.add(name)

    def is_local(name):
        for s in reversed(scopes):
            if name in s:
                return True
        return False

    push_scope()

    while i < n:
        t = tokens[i]

        if t.type == T_OP and t.value == ":":
            i += 1
            while i < n:
                if tokens[i].type == T_OP and tokens[i].value in ("=", ",", ")", "}"):
                    break
                i += 1
            continue

        if t.type == T_IDENT and t.value == "local" and i + 1 < n and tokens[i + 1].type == T_IDENT and tokens[i + 1].value == "function":
            i += 2
            if i < n and tokens[i].type == T_IDENT:
                declare(tokens[i].value)
                push_scope()
                i += 1
                if i < n and tokens[i].type == T_OP and tokens[i].value == "(":
                    i += 1
                    while i < n and not (tokens[i].type == T_OP and tokens[i].value == ")"):
                        if tokens[i].type == T_IDENT:
                            declare(tokens[i].value)
                        i += 1
            continue

        if t.type == T_IDENT and t.value == "local":
            i += 1
            while i < n and tokens[i].type == T_IDENT:
                declare(tokens[i].value)
                i += 1
                if i < n and tokens[i].type == T_OP and tokens[i].value == ",":
                    i += 1
                else:
                    break
            continue

        if t.type == T_IDENT and t.value == "function":
            i += 1
            if i < n and tokens[i].type == T_IDENT:
                i += 1
                if i < n and tokens[i].type == T_OP and tokens[i].value in (".", ":"):
                    i += 1
                    if i < n and tokens[i].type == T_IDENT:
                        i += 1
                push_scope()
                if i < n and tokens[i].type == T_OP and tokens[i].value == "(":
                    i += 1
                    while i < n and not (tokens[i].type == T_OP and tokens[i].value == ")"):
                        if tokens[i].type == T_IDENT:
                            declare(tokens[i].value)
                        i += 1
            continue

        if t.type == T_IDENT and t.value == "for":
            push_scope()
            i += 1
            while i < n and tokens[i].type == T_IDENT:
                declare(tokens[i].value)
                i += 1
                if i < n and tokens[i].type == T_OP and tokens[i].value == ",":
                    i += 1
                else:
                    break
            continue

        if t.type == T_IDENT and t.value == "do":
            push_scope()
            i += 1
            continue

        if t.type == T_IDENT and t.value in ("end", "until"):
            pop_scope()
            i += 1
            continue

        if t.type == T_OP and t.value in (".", ":") and i + 1 < n and tokens[i + 1].type == T_IDENT:
            i += 2
            continue

        if t.type == T_STRING and i + 1 < n and tokens[i + 1].type == T_OP and tokens[i + 1].value == ":":
            i += 2
            if i < n and tokens[i].type == T_IDENT:
                i += 1
            continue

        if t.type == T_IDENT:
            val = t.value
            if val not in KEYWORDS and not val.startswith("__") and val != "_":
                if not is_local(val):
                    global_reads.add(val)
            i += 1
            continue

        i += 1

    pop_scope()
    renameable = declared - global_reads
    return renameable, declared | global_reads


def _build_rename_map(renameable, all_used):
    """Map local identifiers to shortest possible names."""
    reserved = set(KEYWORDS)
    reserved.update({"_G", "_ENV", "_VERSION", "_", "self", "arg", "nil", "true", "false"})

    candidates = []
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
    for c in chars:
        if c not in reserved:
            candidates.append(c)
    for c1 in chars:
        for c2 in chars + "0123456789":
            s = c1 + c2
            if s not in reserved:
                candidates.append(s)
    for c1 in chars:
        for c2 in chars + "0123456789":
            for c3 in chars + "0123456789":
                s = c1 + c2 + c3
                if s not in reserved:
                    candidates.append(s)

    rename = {}
    idx = 0
    for name in sorted(renameable):
        if name in reserved or name.startswith("__"):
            continue
        if len(name) == 1:
            continue
        while idx < len(candidates) and candidates[idx] in all_used:
            idx += 1
        if idx < len(candidates):
            rename[name] = candidates[idx]
            idx += 1
    return rename


def minify(src, convert_long_strings=True, rename_vars=True):
    tokens = tokenize(src)

    stripped = [t for t in tokens if t.type != T_COMMENT]

    rename_map = {}
    if rename_vars:
        declared, used = _collect_scopes(stripped)
        rename_map = _build_rename_map(declared, used)

    out = []
    table_depth = 0
    paren_depth = 0

    for k in range(len(stripped)):
        cur = stripped[k]
        if cur.type == T_EOF:
            break

        if cur.type == T_OP and cur.value == ";":
            if table_depth > 0:
                pass
            else:
                nxt = stripped[k + 1] if k + 1 < len(stripped) else Token(T_EOF, "")
                if not _need_semicolon(cur, nxt):
                    continue

        if convert_long_strings and cur.type == T_STRING and cur.value.startswith("["):
            converted = _long_string_to_short(cur.value)
            if converted is not None:
                cur = Token(T_STRING, converted)

        if cur.type == T_STRING:
            cur = Token(T_STRING, _normalize_short_string(cur.value))

        if rename_vars and cur.type == T_IDENT and cur.value in rename_map:
            cur = Token(T_IDENT, rename_map[cur.value])

        if out:
            prev_token = _last_real_token(stripped, k)
            if prev_token is not None and _need_space(prev_token, cur):
                out.append(" ")

        if cur.type == T_OP:
            if cur.value == "{":
                table_depth += 1
            elif cur.value == "}":
                table_depth = max(0, table_depth - 1)
            elif cur.value == "(":
                paren_depth += 1
            elif cur.value == ")":
                paren_depth = max(0, paren_depth - 1)

        out.append(cur.value)

    return "".join(out) + "\n"


def _last_real_token(stripped, k):
    j = k - 1
    while j >= 0:
        t = stripped[j]
        if t.type == T_OP and t.value == ";":
            nxt = stripped[j + 1] if j + 1 < len(stripped) else Token(T_EOF, "")
            if _need_semicolon(t, nxt):
                return t
            j -= 1
            continue
        return t
    return None

def is_text_file(filepath: str) -> bool:
    _, ext = os.path.splitext(filepath)
    return ext.lower() in TEXT_EXTENSIONS


def is_lua_file(filepath: str) -> bool:
    _, ext = os.path.splitext(filepath)
    return ext.lower() in LUA_EXTENSIONS


def is_img_file(filepath: str) -> bool:
    _, ext = os.path.splitext(filepath)
    return ext.lower() in IMG_EXTENSIONS


def process_file(filepath: str, rel_path: str) -> None:
    if is_img_file(filepath):
        out_path = os.path.join(COMPRESSED_DIR, rel_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(filepath, "rb") as f:
            data = f.read()
        with open(out_path, "wb") as f:
            f.write(data)
        print(f"  [copy] {rel_path}: {len(data):,} bytes (uncompressed)")
        return

    if is_text_file(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if is_lua_file(filepath):
            original_len = len(content)
            content = minify(content)
            minified_len = len(content)
            print(f"  [minify] {rel_path}: {original_len:,} -> {minified_len:,} chars")

        content = content.replace(OLD_URL, NEW_URL)
        raw_bytes = content.encode("utf-8")
    else:
        with open(filepath, "rb") as f:
            raw_bytes = f.read()

    compressed = lz4.block.compress(raw_bytes, store_size=True)

    if is_lua_file(filepath):
        encoded = base64.b64encode(compressed).decode("ascii")
        lua_content = LUA_DECOMPRESSOR.replace("__BASE64_PAYLOAD__", encoded)
        out_bytes = lua_content.encode("utf-8")

        out_path = os.path.join(COMPRESSED_DIR, rel_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        with open(out_path, "wb") as f:
            f.write(out_bytes)

        original_size = len(raw_bytes)
        final_size = len(out_bytes)
        ratio = (1 - final_size / original_size) * 100 if original_size > 0 else 0
        print(f"  {rel_path}: {original_size:,} -> {final_size:,} bytes ({ratio:+.1f}%) [lua wrapper]")
    else:
        encoded = base64.b64encode(compressed)

        out_path = os.path.join(COMPRESSED_DIR, rel_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        with open(out_path, "wb") as f:
            f.write(encoded)

        original_size = len(raw_bytes)
        final_size = len(encoded)
        ratio = (1 - final_size / original_size) * 100 if original_size > 0 else 0
        print(f"  {rel_path}: {original_size:,} -> {final_size:,} bytes ({ratio:+.1f}%)")


def main():
    print(f"Root directory: {ROOT_DIR}")
    print(f"Output directory: {COMPRESSED_DIR}")
    print()

    os.makedirs(COMPRESSED_DIR, exist_ok=True)
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(ROOT_DIR):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]

        for filename in filenames:
            if filename in EXCLUDED_FILES:
                continue

            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, ROOT_DIR)

            process_file(filepath, rel_path)
            file_count += 1

    print(f"\nDone! Processed {file_count} files into '{COMPRESSED_DIR}'")


if __name__ == "__main__":
    main()