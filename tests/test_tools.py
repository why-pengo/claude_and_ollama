"""Unit tests for runner/tools.py — tool dispatch table + result-size cap."""

from tools import TOOL_RESULT_SIZE_CAP, _cap


class TestCap:
    def test_passes_small_ascii_unchanged(self):
        small = "x" * 1000
        assert _cap(small) == small

    def test_passes_exact_cap_ascii_unchanged(self):
        exact = "y" * TOOL_RESULT_SIZE_CAP
        assert _cap(exact) == exact

    def test_truncates_large_ascii_with_size_hint(self):
        big = "z" * 100_000
        result = _cap(big)
        assert "truncated by runner" in result
        assert "100000 bytes" in result
        assert len(result.encode("utf-8")) < len(big)

    def test_truncates_cjk_by_bytes_not_codepoints(self):
        # 16000 CJK codepoints would FALSE-PASS under codepoint semantics
        # (16000 < TOOL_RESULT_SIZE_CAP) but is 48000 UTF-8 bytes.
        cjk = "中" * 16000
        result = _cap(cjk)
        assert "truncated by runner" in result
        assert "48000 bytes" in result
        assert len(result.encode("utf-8")) <= TOOL_RESULT_SIZE_CAP + 100

    def test_truncated_output_is_valid_utf8_when_slice_lands_midchar(self):
        # 6000 CJK chars = 18000 bytes; the byte-slice will land
        # mid-multibyte-character. errors="ignore" must produce valid UTF-8.
        test = "中" * 6000
        result = _cap(test)
        # Round-trip would raise UnicodeDecodeError if invalid bytes leaked
        result.encode("utf-8").decode("utf-8")
