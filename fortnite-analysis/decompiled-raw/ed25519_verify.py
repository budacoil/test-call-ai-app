import hashlib
P = 2 ** 255 - 19
Q = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
I = pow(2, (P - 1) // 4, P)

def _inv(x: int) -> int:
    return pow(x, P - 2, P)

def _x_recover(y: int):
    xx = (y * y - 1) * _inv(D * y * y + 1) % P
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P != 0:
        x = x * I % P
    if (x * x - xx) % P != 0:
        return
    if x % 2 == 0:
        return x
    return P - x

_BY = 4 * _inv(5) % P
_BX = _x_recover(_BY)
_B = _BX, _BY, 1, _BX * _BY % P
_ZERO = (0, 1, 1, 0)

def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    A = (y1 - x1) * (y2 - x2) % P
    B = (y1 + x1) * (y2 + x2) % P
    C = t1 * 2 * D * t2 % P
    E = z1 * 2 * z2 % P
    F, G, H, J = B - A, E - C, E + C, B + A
    return F * G % P, H * J % P, G * H % P, F * J % P

def _mul(s: int, pt):
    r = _ZERO
    while s:
        if s & 1:
            r = _add(r, pt)
        pt = _add(pt, pt)
        s >>= 1
    return r

def _decode(b: bytes):
    if len(b) != 32:
        return
    y = int.from_bytes(b, 'little')
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= P:
        return
    x = _x_recover(y)
    if x is None or x == 0 and sign:
        return
    if x & 1 != sign:
        x = P - x
    return x, y, 1, x * y % P

def _eq(a, b) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % P == 0 and (a[1] * b[2] - b[1] * a[2]) % P == 0

def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    try:
        if len(public_key) != 32 or len(signature) != 64:
            return False
        a = _decode(public_key)
        r = _decode(signature[:32])
        s = int.from_bytes(signature[32:], 'little')
        if a is None or r is None or s >= Q:
            return False
        h = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), 'little') % Q
        return _eq(_mul(s, _B), _add(r, _mul(h, a)))
    except Exception:
        return False

