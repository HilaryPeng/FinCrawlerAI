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
    
    if len(code) == 6 and code.isdigit():
        if code.startswith("6"):
            return f"sh{code}"
        elif code.startswith("0") or code.startswith("3"):
            return f"sz{code}"
        elif code.startswith("8") or code.startswith("4"):
            return f"bj{code}"
    
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
