"""
Abacus Practice Sheet Generator
================================
Streamlit + fpdf2 application that generates randomized Abacus practice PDFs
matching the reference layout exactly.

Sections:
  1.1  Calculate Mentally  – 5 vertical number stacks with answer box
  1.2  Draw the beads      – 3 empty abacus rods with circled number below
  1.3  Write the value     – 2 abacus rods with beads drawn; empty answer box
  1.4  Calculate (Abacus)  – 10-column table, 3 data rows + 2 answer rows
  Footer                   – REMARKS box + Instructor's Signature
"""

import random
import io
from fpdf import FPDF
import streamlit as st

# ============================================================
# 1.  ABACUS LOGIC
# ============================================================

def _bead_state(value: int):
    """Return (lower_beads 0-4, upper_bead 0|5) for a digit 0-9."""
    upper = 5 if value >= 5 else 0
    lower = value - upper
    return lower, upper


def _can_add_direct(current: int, delta: int) -> bool:
    """
    Class 1 – Direct sums only (no 5-complement, no 10-complement).

    A move is 'direct' if it only slides lower beads up/down OR only
    moves the upper (5) bead, without needing a complementary exchange.

    Rules:
      - Adding delta > 0: the upper bead must not change direction
        (i.e. we don't put down the 5-bead while lifting lower beads).
      - Subtracting delta < 0: symmetric.
    """
    target = current + delta
    if target < 0 or target > 9:
        return False
    cl, cu = _bead_state(current)
    tl, tu = _bead_state(target)
    dl = tl - cl   # change in lower beads
    du = tu - cu   # change in upper bead (0 or ±5)

    if delta > 0:
        # Direct add: either only lower beads move up, or only upper bead moves down
        # (putting the 5-bead down while lower beads go up = 5-complement → NOT allowed)
        if du < 0 and dl > 0:   # 5-complement: put down 5, lift lower → not direct
            return False
        if dl < 0:               # lower beads going down while adding → impossible direct
            return False
        return True
    else:
        # Direct subtract: either only lower beads move down, or only upper bead moves up
        if du > 0 and dl < 0:   # 5-complement: lift 5, put down lower → not direct
            return False
        if dl > 0:
            return False
        return True


def generate_class1(n_numbers: int = 3, digits: int = 1) -> list:
    """
    Class 1: Direct sums only, no 5-complement, no 10-complement.
    Each column of a multi-digit number is checked independently.
    Running sum stays in [0, 10^digits - 1].
    """
    max_val = 10 ** digits - 1
    for _ in range(8000):
        first = random.randint(1, max_val)
        nums = [first]
        current = first
        ok = True
        for _ in range(n_numbers - 1):
            candidates = []
            for v in range(-max_val, max_val + 1):
                if v == 0:
                    continue
                new_val = current + v
                if new_val < 0 or new_val > max_val:
                    continue
                # Check every digit column independently.
                # Use the isolated digit of v for that column — NOT d_new - d_cur,
                # because d_new already has any carry baked in, which gives a
                # wrong (smaller) delta and lets carry-producing moves slip through.
                col_ok = True
                for col in range(digits):
                    d_cur = (current // (10 ** col)) % 10
                    # Isolated contribution of v to this column (sign-aware)
                    col_delta = (abs(v) // (10 ** col)) % 10
                    if v < 0:
                        col_delta = -col_delta
                    if not _can_add_direct(d_cur, col_delta):
                        col_ok = False
                        break
                if col_ok:
                    candidates.append(v)
            if not candidates:
                ok = False
                break
            v = random.choice(candidates)
            nums.append(v)
            current += v
        if ok and len(nums) == n_numbers:
            return nums
    return _fallback_sequence(n_numbers, digits)


def _is_small_friend(current: int, v: int, digits: int) -> bool:
    """
    Return True if adding v to current requires a 5-complement in at least
    one column AND does NOT require a 10-complement carry in any column.

    A 5-complement move is one that:
    - Cannot be done directly (would need to exchange the 5-bead with lower beads)
    - Stays within 0-9 in every column (no carry to the next column)
    """
    new_val = current + v
    if new_val < 0 or new_val > (10 ** digits - 1):
        return False
    needs_5comp = False
    for col in range(digits):
        d_cur = (current // (10 ** col)) % 10
        col_delta = (abs(v) // (10 ** col)) % 10
        if v < 0:
            col_delta = -col_delta
        raw = d_cur + col_delta
        if raw < 0 or raw > 9:
            return False   # 10-complement carry — not Class 2
        if not _can_add_direct(d_cur, col_delta):
            needs_5comp = True  # within 0-9 but not direct = 5-complement
    return needs_5comp


def _is_no_carry(current: int, v: int, digits: int) -> bool:
    """
    Return True if adding v to current stays within 0-9 in every column
    (no 10-complement carry between columns). Both direct and small-friend
    moves satisfy this — it's the Class 2 upper bound.
    """
    new_val = current + v
    if new_val < 0 or new_val > (10 ** digits - 1):
        return False
    for col in range(digits):
        d_cur = (current // (10 ** col)) % 10
        col_delta = (abs(v) // (10 ** col)) % 10
        if v < 0:
            col_delta = -col_delta
        if d_cur + col_delta < 0 or d_cur + col_delta > 9:
            return False
    return True


def generate_class2(n_numbers: int = 3, digits: int = 1) -> list:
    """
    Class 2: 5-complement (small friend) moves.

    Rules:
    - No 10-complement carry between columns (each column stays 0-9).
    - At least one step in the sequence MUST be a small-friend move
      (requires 5-complement in at least one column).
    - Small-friend candidates are strongly preferred over direct moves
      so the sheet feels distinctly Class 2.

    Strategy:
    - For each step, collect small-friend candidates and direct candidates.
    - Pick from small-friend pool with 80% probability if available,
      otherwise fall back to direct.
    - After building the sequence, reject it if no step used small-friend.
    """
    max_val = 10 ** digits - 1
    for _ in range(8000):
        first = random.randint(1, max_val)
        nums = [first]
        current = first
        ok = True
        has_small_friend = False

        for _ in range(n_numbers - 1):
            sf_candidates = []
            direct_candidates = []

            for v in range(-max_val, max_val + 1):
                if v == 0:
                    continue
                if _is_small_friend(current, v, digits):
                    sf_candidates.append(v)
                elif _is_no_carry(current, v, digits) and not _is_small_friend(current, v, digits):
                    # Pure direct move: no 5-complement, no 10-complement
                    col_direct = True
                    for col in range(digits):
                        d_cur = (current // (10 ** col)) % 10
                        col_delta = (abs(v) // (10 ** col)) % 10
                        if v < 0:
                            col_delta = -col_delta
                        if not _can_add_direct(d_cur, col_delta):
                            col_direct = False
                            break
                    if col_direct:
                        direct_candidates.append(v)

            if not sf_candidates and not direct_candidates:
                ok = False
                break

            # 80% chance to pick small-friend if available
            if sf_candidates and (not direct_candidates or random.random() < 0.80):
                v = random.choice(sf_candidates)
                has_small_friend = True
            elif direct_candidates:
                v = random.choice(direct_candidates)
            else:
                v = random.choice(sf_candidates)
                has_small_friend = True

            nums.append(v)
            current += v

        # Reject sequences with no small-friend step
        if ok and has_small_friend and len(nums) == n_numbers:
            return nums

    return _fallback_sequence(n_numbers, digits)


def _requires_ten_complement(current: int, v: int, digits: int) -> bool:
    """
    Return True if adding v to current requires a 10-complement carry/borrow
    in at least one column.

    A 10-complement carry/borrow occurs when a column's intermediate sum
    goes below 0 (borrow) or reaches 10+ (carry) — i.e. the raw column
    arithmetic without carry would overflow or underflow the 0-9 range.

    For single-digit: simply check if the ones column overflows/underflows.
    For multi-digit: check each column's isolated arithmetic.
    """
    for col in range(digits):
        d_cur = (current // (10 ** col)) % 10
        # Isolated delta for this column (ignoring carries from lower columns)
        col_delta = (abs(v) // (10 ** col)) % 10
        if v < 0:
            col_delta = -col_delta
        raw = d_cur + col_delta
        # If raw goes outside 0-9, a 10-complement carry/borrow is needed
        if raw < 0 or raw > 9:
            return True
    return False


def generate_class3(n_numbers: int = 3, digits: int = 1) -> list:
    """
    Class 3: Big Friend (10-complement carry-overs) ONLY.

    Every step in the sequence must require a 10-complement carry or borrow
    in at least one column. Steps that can be solved purely with direct moves
    or 5-complement (small friend) are excluded — those belong to Class 1/2.

    Running sum stays in [0, 10^digits - 1].
    """
    max_val = 10 ** digits - 1
    for _ in range(8000):
        first = random.randint(1, max_val)
        nums = [first]
        current = first
        ok = True
        for _ in range(n_numbers - 1):
            candidates = []
            for v in range(-current, max_val - current + 1):
                if v == 0:
                    continue
                # Must require a 10-complement carry/borrow in at least one column
                if _requires_ten_complement(current, v, digits):
                    candidates.append(v)
            if not candidates:
                ok = False
                break
            v = random.choice(candidates)
            nums.append(v)
            current += v
        if ok and len(nums) == n_numbers:
            return nums
    return _fallback_sequence(n_numbers, digits)


def _fallback_sequence(n: int, digits: int) -> list:
    """Simple safe fallback that always works."""
    max_val = 10 ** digits - 1
    nums = [random.randint(1, max(1, max_val // 3))]
    for _ in range(n - 1):
        nums.append(random.randint(1, max(1, max_val // 4)))
    return nums


def generate_sequence(class_num: int, n_numbers: int = 3, digits: int = 1) -> list:
    """
    Generate a sequence of numbers for the given class and digit count.
    digits=0 means 'mixed' — randomly pick 1 or 2 digits per call.

    Special rule: Class 3 (big friend / 10-complement) requires at least
    2 digits because a 10-complement carry must cross into the tens column.
    If digits=1 is requested for Class 3, it is silently upgraded to 2.
    """
    if digits == 0:
        effective_digits = random.choice([1, 2])
    else:
        effective_digits = digits

    # Class 3 needs at least 2 digits for 10-complement to be possible
    if class_num == 3 and effective_digits == 1:
        effective_digits = 2

    if class_num == 1:
        return generate_class1(n_numbers, effective_digits)
    elif class_num == 2:
        return generate_class2(n_numbers, effective_digits)
    else:
        return generate_class3(n_numbers, effective_digits)


# ============================================================
# 2.  ABACUS DRAWING HELPERS
# ============================================================

def draw_bead(pdf: FPDF, cx: float, cy: float, r: float = 2.0, filled: bool = True):
    """
    Draw a diamond-shaped abacus bead centred at (cx, cy).
    Uses a filled/outlined ellipse to approximate the classic bead shape.
    """
    w = r * 2.2
    h = r * 1.4
    if filled:
        pdf.set_fill_color(0, 0, 0)
        pdf.ellipse(cx - w / 2, cy - h / 2, w, h, style="F")
    else:
        pdf.set_fill_color(255, 255, 255)
        pdf.set_draw_color(0, 0, 0)
        pdf.ellipse(cx - w / 2, cy - h / 2, w, h, style="D")


def draw_abacus_rod_empty(pdf: FPDF, cx: float, y_top: float,
                           label: str = "O", rod_h: float = 28,
                           beam_offset: float = 9):
    """
    Draw a single empty abacus rod (vertical line + horizontal beam).
    The upper section is completely blank — no bead drawn above the beam.
    Students draw their own beads here.
    cx      = horizontal centre of the rod
    y_top   = top of the rod (below the column label)
    """
    beam_y = y_top + beam_offset

    # Column label
    pdf.set_font("Helvetica", size=7)
    pdf.set_xy(cx - 4, y_top - 5)
    pdf.cell(8, 4, label, align="C")

    # Vertical rod
    pdf.set_line_width(0.5)
    pdf.set_draw_color(0, 0, 0)
    pdf.line(cx, y_top, cx, y_top + rod_h)

    # Horizontal beam
    pdf.set_line_width(0.9)
    pdf.line(cx - 5, beam_y, cx + 5, beam_y)
    pdf.set_line_width(0.4)
    # No bead drawn above the beam — upper section is intentionally blank


def draw_abacus_rod_with_beads(pdf: FPDF, cx: float, y_top: float,
                                digit: int, label: str = "O",
                                rod_h: float = 28, beam_offset: float = 9):
    """
    Draw a single abacus rod with beads representing `digit` (0-9).

    Upper section (above beam): 1 bead slot.
      - Filled (black) if digit >= 5, pushed DOWN against the beam.
      - Empty (outline) if digit < 5, sitting UP away from the beam.

    Lower section (below beam): 4 bead slots.
      - `lower_val` filled beads are packed UP against the beam (touching).
      - Remaining empty beads hang DOWN away from the beam.
      - Consecutive filled beads touch each other for a real-abacus feel.
    """
    BEAD_R  = 2.0          # bead radius (half-height)
    BEAD_H  = BEAD_R * 1.4 # full bead height (ellipse h)
    GAP     = 0.0          # gap between touching beads (0 = flush contact)
    STEP    = BEAD_H + GAP # centre-to-centre distance for touching beads

    beam_y     = y_top + beam_offset
    upper_val  = 5 if digit >= 5 else 0
    lower_val  = digit - upper_val

    # ── Column label ──────────────────────────────────────────
    pdf.set_font("Helvetica", size=7)
    pdf.set_xy(cx - 4, y_top - 5)
    pdf.cell(8, 4, label, align="C")

    # ── Vertical rod ──────────────────────────────────────────
    pdf.set_line_width(0.5)
    pdf.set_draw_color(0, 0, 0)
    pdf.line(cx, y_top, cx, y_top + rod_h)

    # ── Horizontal beam ───────────────────────────────────────
    pdf.set_line_width(0.9)
    pdf.line(cx - 5, beam_y, cx + 5, beam_y)
    pdf.set_line_width(0.4)

    # ── Upper bead (1 slot above beam) ────────────────────────
    # Active (filled): pushed down, centre just above beam
    # Inactive (empty): floats up, centre further from beam
    if upper_val == 5:
        upper_cy = beam_y - BEAD_R - 0.5   # touching the beam from above
    else:
        upper_cy = beam_y - BEAD_R * 2.5   # resting up near the top
    draw_bead(pdf, cx, upper_cy, r=BEAD_R, filled=(upper_val == 5))

    # ── Lower beads (4 slots below beam) ─────────────────────
    # Active beads: packed tightly UP against the beam (slot 0 = closest).
    # Inactive beads: packed tightly DOWN at the bottom of the rod.
    #
    # Layout (slot 0 = nearest beam, slot 3 = furthest):
    #   slots 0 .. lower_val-1  → filled, stacked up from beam
    #   slots lower_val .. 3    → empty,  stacked down from rod bottom

    # Positions for filled beads (grow downward from beam)
    for slot in range(lower_val):
        by = beam_y + BEAD_R + 0.5 + slot * STEP
        draw_bead(pdf, cx, by, r=BEAD_R, filled=True)

    # Positions for empty beads (grow upward from rod bottom)
    n_empty = 4 - lower_val
    rod_bottom = y_top + rod_h
    for slot in range(n_empty):
        by = rod_bottom - BEAD_R - 0.5 - slot * STEP
        draw_bead(pdf, cx, by, r=BEAD_R, filled=False)


def draw_full_abacus_empty(pdf: FPDF, x_left: float, y_top: float, digits: int = 1):
    """
    Draw a complete empty abacus (1 or 2 rods) for section 1.2.
    x_left = left edge of the abacus drawing area.
    """
    rod_gap = 14  # horizontal gap between rod centres
    if digits == 1:
        draw_abacus_rod_empty(pdf, x_left + 5, y_top, label="O")
    else:
        draw_abacus_rod_empty(pdf, x_left + 3, y_top, label="T")
        draw_abacus_rod_empty(pdf, x_left + 3 + rod_gap, y_top, label="O")


def draw_full_abacus_with_beads(pdf: FPDF, x_left: float, y_top: float,
                                 value: int, digits: int = 1):
    """
    Draw a complete abacus with beads representing `value` for section 1.3.
    """
    rod_gap = 14
    if digits == 1:
        draw_abacus_rod_with_beads(pdf, x_left + 5, y_top, value % 10, label="O")
    else:
        tens_digit = (value // 10) % 10
        ones_digit = value % 10
        draw_abacus_rod_with_beads(pdf, x_left + 3, y_top, tens_digit, label="T")
        draw_abacus_rod_with_beads(pdf, x_left + 3 + rod_gap, y_top, ones_digit, label="O")


# ============================================================
# 3.  PDF GENERATION
# ============================================================

class AbacusPDF(FPDF):
    pass   # No custom header/footer needed


def build_pdf(class_num: int, digits: int) -> bytes:
    """
    Build the complete A4 practice sheet and return raw PDF bytes.
    digits: 1 = 1-digit, 2 = 2-digit, 0 = mixed (1 and 2 digit problems)
    """
    # For abacus rod drawing sections (1.2 / 1.3) we need a concrete rod count.
    # Mixed mode uses 2-rod abacus diagrams so both digit widths are covered.
    abacus_digits = 2 if digits == 0 else digits
    pdf = AbacusPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)

    # ── Page geometry ──────────────────────────────────────────
    PAGE_W   = 210
    PAGE_H   = 297
    ML       = 12          # left margin
    MR       = 12          # right margin
    CW       = PAGE_W - ML - MR   # usable content width = 186 mm

    # ── Colours ────────────────────────────────────────────────
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)
    LGRAY = (220, 220, 220)

    def set_black():
        pdf.set_draw_color(*BLACK)
        pdf.set_text_color(*BLACK)

    set_black()

    # ===========================================================
    # HEADER BAR
    # ===========================================================
    pdf.set_fill_color(*LGRAY)
    pdf.rect(ML, 8, CW, 8, style="FD")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*BLACK)

    pdf.set_xy(ML + 1, 8)
    pdf.cell(CW / 3, 8, f"Class {class_num}", align="L")

    pdf.set_xy(ML + CW / 3, 8)
    pdf.cell(CW / 3, 8, "ABACUS PRACTICE SHEET", align="C")

    pdf.set_xy(ML + 2 * CW / 3, 8)
    pdf.cell(CW / 3 - 1, 8,
             f"{digits} Digit{'s' if digits > 1 else ''}", align="R")

    # ===========================================================
    # SECTION 1.1 – Calculate Mentally
    # ===========================================================
    S11_Y = 20          # top of section
    BLOCK_W = 20        # width of each number block
    BLOCK_ROW_H = 6.5   # height of each number row inside block
    N_ROWS = 3          # numbers per problem
    ANS_H = 7           # answer box height
    N_PROBS = 5         # number of problem columns

    # Section heading
    pdf.set_font("Helvetica", "BU", 10)
    pdf.set_xy(ML, S11_Y)
    pdf.cell(70, 6, "1.1 Calculate Mentally")

    # Score circle  ➄
    _draw_score_circle(pdf, PAGE_W - MR - 6, S11_Y + 3, "5")

    # Generate problems
    problems_11 = [generate_sequence(class_num, N_ROWS, digits) for _ in range(N_PROBS)]

    # Distribute blocks evenly across content width
    total_blocks_w = N_PROBS * BLOCK_W
    gap = (CW - total_blocks_w) / (N_PROBS + 1)

    box_top = S11_Y + 8

    for ci, nums in enumerate(problems_11):
        bx = ML + gap + ci * (BLOCK_W + gap)

        # Outer border for the number stack
        pdf.set_line_width(0.35)
        pdf.rect(bx, box_top, BLOCK_W, N_ROWS * BLOCK_ROW_H)

        # Individual number rows (internal horizontal lines)
        pdf.set_font("Helvetica", size=9)
        for ri, num in enumerate(nums):
            ry = box_top + ri * BLOCK_ROW_H
            if ri > 0:
                pdf.line(bx, ry, bx + BLOCK_W, ry)
            pdf.set_xy(bx, ry)
            pdf.cell(BLOCK_W, BLOCK_ROW_H, str(num), align="C")

        # Answer box below
        ans_y = box_top + N_ROWS * BLOCK_ROW_H + 2
        pdf.rect(bx, ans_y, BLOCK_W, ANS_H)

    # Bottom of section 1.1
    S11_BOTTOM = box_top + N_ROWS * BLOCK_ROW_H + ANS_H + 6

    # ===========================================================
    # SECTIONS 1.2 & 1.3  (side by side)
    # ===========================================================
    S12_Y = S11_BOTTOM + 4
    DIVIDER_X = ML + CW * 0.50   # vertical divider between 1.2 and 1.3

    ROD_H = 28
    BEAM_OFF = 9
    ROD_AREA_Y = S12_Y + 9       # top of rod drawing area

    # ── 1.2 heading ────────────────────────────────────────────
    pdf.set_font("Helvetica", "BU", 10)
    pdf.set_xy(ML, S12_Y)
    pdf.cell(55, 6, "1.2 Draw the beads.")

    # ── 1.3 heading ────────────────────────────────────────────
    pdf.set_font("Helvetica", "BU", 10)
    pdf.set_xy(DIVIDER_X + 6, S12_Y)
    pdf.cell(80, 6, "1.3  Write the value of beads")

    # Score circle ➄ for 1.3
    _draw_score_circle(pdf, PAGE_W - MR - 6, S12_Y + 3, "5")

    # ── Vertical double-headed arrow between 1.2 and 1.3 ───────
    arr_x  = DIVIDER_X + 2
    arr_y1 = S12_Y + 2
    arr_y2 = S12_Y + 46
    pdf.set_line_width(0.7)
    pdf.line(arr_x, arr_y1, arr_x, arr_y2)
    # Top arrowhead
    pdf.line(arr_x, arr_y1, arr_x - 2.5, arr_y1 + 5)
    pdf.line(arr_x, arr_y1, arr_x + 2.5, arr_y1 + 5)
    # Bottom arrowhead
    pdf.line(arr_x, arr_y2, arr_x - 2.5, arr_y2 - 5)
    pdf.line(arr_x, arr_y2, arr_x + 2.5, arr_y2 - 5)
    pdf.set_line_width(0.35)

    # ── 1.2: 3 empty abacus rods ───────────────────────────────
    max_val = 10 ** abacus_digits - 1
    nums_12 = [random.randint(10 if abacus_digits > 1 else 1, max_val) for _ in range(3)]

    abacus_w = 22 if abacus_digits == 1 else 32   # width per abacus unit
    spacing_12 = (DIVIDER_X - ML - 3 * abacus_w) / 4

    for i, num in enumerate(nums_12):
        ax = ML + spacing_12 + i * (abacus_w + spacing_12)
        draw_full_abacus_empty(pdf, ax, ROD_AREA_Y, abacus_digits)

        # Circled number below rod
        circ_cx = ax + (abacus_w / 2)
        circ_y  = ROD_AREA_Y + ROD_H + 4
        circ_rw = 9 if num >= 10 else 7
        pdf.set_line_width(0.4)
        pdf.ellipse(circ_cx - circ_rw / 2, circ_y, circ_rw, 6.5, style="D")
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_xy(circ_cx - circ_rw / 2, circ_y)
        pdf.cell(circ_rw, 6.5, str(num), align="C")

    # ── 1.3: 2 abacus rods with beads ──────────────────────────
    nums_13 = [random.randint(10 if abacus_digits > 1 else 1, max_val) for _ in range(2)]

    s13_left = DIVIDER_X + 8
    s13_right = PAGE_W - MR
    s13_w = s13_right - s13_left
    spacing_13 = (s13_w - 2 * abacus_w) / 3

    for i, num in enumerate(nums_13):
        ax = s13_left + spacing_13 + i * (abacus_w + spacing_13)
        draw_full_abacus_with_beads(pdf, ax, ROD_AREA_Y, num, abacus_digits)

        # Answer box below
        ans_y = ROD_AREA_Y + ROD_H + 4
        box_w = abacus_w - 2
        pdf.set_line_width(0.35)
        pdf.rect(ax + 1, ans_y, box_w, 7)

    S12_BOTTOM = ROD_AREA_Y + ROD_H + 4 + 7 + 6

    # ===========================================================
    # SECTION 1.4 – Calculate (Using Abacus)
    # ===========================================================
    S14_Y = S12_BOTTOM + 4

    pdf.set_font("Helvetica", "BU", 10)
    pdf.set_xy(ML, S14_Y)
    pdf.cell(80, 6, "1.4  Calculate (Using Abacus)")

    # Score circle ⑳
    _draw_score_circle(pdf, PAGE_W - MR - 7, S14_Y + 3, "20", r_w=12)

    # Table layout
    TABLE_Y    = S14_Y + 9
    N_COLS     = 10
    N_DATA     = 3    # rows of numbers
    N_ANS      = 2    # blank answer rows
    COL_W      = CW / N_COLS
    ROW_H      = 7.5

    # Generate 10 problem columns
    problems_14 = [generate_sequence(class_num, N_DATA, digits) for _ in range(N_COLS)]

    pdf.set_line_width(0.35)

    # Header row  1 … 10
    pdf.set_font("Helvetica", "B", 9)
    for ci in range(N_COLS):
        cx = ML + ci * COL_W
        pdf.rect(cx, TABLE_Y, COL_W, ROW_H)
        pdf.set_xy(cx, TABLE_Y)
        pdf.cell(COL_W, ROW_H, str(ci + 1), align="C")

    # Data rows
    pdf.set_font("Helvetica", size=9)
    for ri in range(N_DATA):
        ry = TABLE_Y + (ri + 1) * ROW_H
        for ci in range(N_COLS):
            cx = ML + ci * COL_W
            pdf.rect(cx, ry, COL_W, ROW_H)
            pdf.set_xy(cx, ry)
            pdf.cell(COL_W, ROW_H, str(problems_14[ci][ri]), align="C")

    # Answer rows (blank)
    for ri in range(N_ANS):
        ry = TABLE_Y + (1 + N_DATA + ri) * ROW_H
        for ci in range(N_COLS):
            cx = ML + ci * COL_W
            pdf.rect(cx, ry, COL_W, ROW_H)

    TABLE_BOTTOM = TABLE_Y + (1 + N_DATA + N_ANS) * ROW_H

    # ===========================================================
    # FOOTER – REMARKS + Instructor's Signature
    # ===========================================================
    FOOTER_Y = TABLE_BOTTOM + 8

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(ML + 18, FOOTER_Y)
    pdf.cell(30, 5, "REMARKS")

    remarks_y = FOOTER_Y + 6
    pdf.set_line_width(0.35)
    pdf.rect(ML + 18, remarks_y, 58, 16)

    # Page number centred
    pdf.set_font("Helvetica", size=8)
    pdf.set_xy(PAGE_W / 2 - 8, remarks_y + 6)
    pdf.cell(16, 5, "1 / 1", align="C")

    # Instructor's Signature (italic, right-aligned)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_xy(PAGE_W - MR - 58, remarks_y + 10)
    pdf.cell(58, 5, "Instructor's Signature", align="R")

    return bytes(pdf.output())


# ── Helper: draw a circled score label ─────────────────────────────────────

def _draw_score_circle(pdf: FPDF, cx: float, cy: float,
                       label: str, r_w: float = 10, r_h: float = 8):
    """Draw a circle with a bold label inside (score indicator)."""
    pdf.set_line_width(0.5)
    pdf.set_draw_color(0, 0, 0)
    pdf.ellipse(cx - r_w / 2, cy - r_h / 2, r_w, r_h, style="D")
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_xy(cx - r_w / 2, cy - r_h / 2)
    pdf.cell(r_w, r_h, label, align="C")


# ============================================================
# 4.  STREAMLIT UI
# ============================================================

def main():
    st.set_page_config(
        page_title="Abacus Practice Sheet Generator",
        page_icon="🧮",
        layout="centered",
    )

    st.title("🧮 Abacus Practice Sheet Generator")
    st.markdown(
        "Configure the worksheet below, then click **Generate & Download PDF** "
        "to get a ready-to-print A4 practice sheet."
    )

    col1, col2 = st.columns(2)
    with col1:
        class_choice = st.selectbox(
            "Select Class",
            options=["Class 1", "Class 2", "Class 3"],
            help=(
                "**Class 1** – Direct sums only (no 5-complement, no carry)\n\n"
                "**Class 2** – 5-complement (small friend) allowed; no column carry\n\n"
                "**Class 3** – 10-complement (big friend) carry only. "
                "Requires 2-digit numbers; 1-digit selection is auto-upgraded."
            ),
        )
    with col2:
        digit_choice = st.selectbox(
            "Select Digits",
            options=["1 Digit", "2 Digits", "Mixed (1 & 2 Digits)"],
            help=(
                "**1 Digit** – Problems use single-digit numbers (0–9)\n\n"
                "**2 Digits** – Problems use two-digit numbers (10–99)\n\n"
                "**Mixed** – Each problem randomly uses 1 or 2 digits"
            ),
        )

    class_num = int(class_choice.split()[1])
    # digits: 1, 2, or 0 (mixed)
    if digit_choice.startswith("Mixed"):
        digits = 0
    else:
        digits = int(digit_choice.split()[0])

    if st.button("📄 Generate & Download PDF", type="primary"):
        with st.spinner("Generating worksheet…"):
            pdf_bytes = build_pdf(class_num, digits)

        st.success("✅ PDF ready!")
        digit_label = "mixed" if digits == 0 else f"{digits}digit"
        st.download_button(
            label="⬇️ Download Practice Sheet",
            data=pdf_bytes,
            file_name=f"abacus_class{class_num}_{digit_label}.pdf",
            mime="application/pdf",
        )

        digit_display = "Mixed (1 & 2 Digits)" if digits == 0 else f"{digits} Digit{'s' if digits > 1 else ''}"
        st.info(
            f"**Class {class_num} | {digit_display}**\n\n"
            "Sheet includes:\n"
            "- **1.1** Calculate Mentally — 5 problems × 3 numbers + answer box\n"
            "- **1.2** Draw the beads — 3 empty abacus rods with target number\n"
            "- **1.3** Write the value — 2 abacus diagrams with beads drawn\n"
            "- **1.4** Calculate Using Abacus — 10-column table, 3 rows + 2 answer rows\n"
            "- Footer: Remarks box + Instructor's Signature"
        )


if __name__ == "__main__":
    main()
