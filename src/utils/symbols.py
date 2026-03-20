"""
Stock symbol normalization utilities.
"""

import re


def normalize_symbol(code: str) -> str:
    """
    Normalize stock code to format: sh600000, sz000001, bjxxxxxx
    
    Args:
        code: Raw stock code (could be 600000, sz600000, sh600000, etc.)
        
    Returns:
        Normalized stock code with market prefix
    """
    if not code:
        return ""
    
    code = str(code).strip().lower()
    
    if code.startswith("sh"):
        return code
    if code.startswith("sz"):
        return code
    if code.startswith("bj"):
        return code

    digits = re.sub(r"[^0-9]", "", code)
    if digits and len(digits) <= 6:
        digits = digits.zfill(6)
        if digits.startswith("6"):
            return f"sh{digits}"
        if digits.startswith("0") or digits.startswith("3"):
            return f"sz{digits}"
        if digits.startswith("8") or digits.startswith("4") or digits.startswith("9"):
            return f"bj{digits}"
    
    return code


def normalize_symbol_list(codes: list) -> list:
    """Normalize a list of stock codes."""
    return [normalize_symbol(c) for c in codes]


def is_valid_symbol(code: str) -> bool:
    """Check if a stock code is valid."""
    if not code:
        return False
    code = str(code).strip().lower()
    return bool(re.match(r'^(sh|sz|bj)\d{6}$', code))


def extract_code_from_symbol(symbol: str) -> str:
    """Extract pure numeric code from symbol."""
    if not symbol:
        return ""
    symbol = str(symbol).strip()
    return re.sub(r'[^0-9]', '', symbol)
