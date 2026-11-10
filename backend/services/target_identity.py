"""Conservative target comparisons shared by operation guards and recovery.

A short name may denote a qualified name. Two different qualified domains never
become equivalent merely because their first label matches. No DNS is consulted.
"""
import ipaddress


def normalized(value):
    return str(value or '').strip().upper().rstrip('.')


def same_target(left, right):
    left, right = normalized(left), normalized(right)
    if not left or not right:
        return False
    if left == right:
        return True
    for name in (left, right):
        try:
            ipaddress.ip_address(name)
            return False
        except ValueError:
            pass
    return ('.' not in left or '.' not in right) and left.split('.')[0] == right.split('.')[0]
