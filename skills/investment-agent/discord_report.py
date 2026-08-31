"""Discord rendering for HOS Stock Watch.

This module has two deliberately different renderers: the private report sent
to Discord and a value-free public summary for CI logs and GitHub summaries.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Iterable, Mapping

from progress_notification import build_progress_snapshot


ACTIVE_FY_DECISIONS = {"BUY_2026_CORE", "BUY_2026_CONDITIONAL"}
RELEVANT_STATUSES = {"READY", "BLOCKED_AT_LIMIT", "BLOCKED_DAILY_ORDER_LIMIT", "NEAR", "ABOVE_CEILING"}
STATUS_LABELS = {
    "READY": "âœ… è³¼å…¥å¯",
    "BLOCKED_AT_LIMIT": "ðŸ›‘ æŒ‡å€¤åˆ°é”",
    "BLOCKED_DAILY_ORDER_LIMIT": "â­ï¸ æ³¨æ–‡ä¸Šé™",
    "NEAR": "ðŸŸ¡ æŒ‡å€¤æŽ¥è¿‘",
    "ABOVE_CEILING": "â¸ï¸ ä¸Šé™è¶…éŽ",
}
STATUS_RANK = {"READY": 0, "BLOCKED_AT_LIMIT": 1, "BLOCKED_DAILY_ORDER_LIMIT": 2, "NEAR": 3, "ABOVE_CEILING": 4}
BLOCK_LABELS = {
    "ACCOUNT_BUDGET_SECRET_REQUIRED": "å£åº§äºˆç®—æœªè¨­å®š",
    "ACCOUNT_BUYING_POWER_REQUIRED": "è²·ä»˜ä½™åŠ›æœªè¨­å®š",
    "ACCOUNT_STRATEGY_BUDGET_EXCEEDED": "å£åº§äºˆç®—è¶…éŽ",
    "ACCOUNT_BUYING_POWER_INSUFFICIENT": "è²·ä»˜ä½™åŠ›ä¸è¶³",
    "ACCOUNT_ANNUAL_STOCK_CAP_EXCEEDED": "å¹´é–“æ ªå¼ä¸Šé™è¶…éŽ",
    "HOUSEHOLD_TARGET_BUDGET_EXCEEDED": "å¹´åº¦æŠ•è³‡æž è¶…éŽ",
    "HOUSEHOLD_RESERVE_BREACH": "ç”Ÿæ´»é˜²è¡›è³‡é‡‘ä¸è¶³",
    "EARNINGS_REVIEW_REQUIRED": "æ±ºç®—ç¢ºèª",
    "ORDER_CONDITION_REVIEW_REQUIRED": "è³¼å…¥æ¡ä»¶ç¢ºèª",
    "STEP_CONDITION_REVIEW_REQUIRED": "æ®µéšŽæ¡ä»¶ç¢ºèª",
    "BENEFIT_RECHECK_REQUIRED": "å„ªå¾…å†ç¢ºèª",
    "PRICE_UNAVAILABLE": "æ ªä¾¡æœªå–å¾—",
    "STALE_PRICE": "æ ªä¾¡ãŒå¤ã„",
    "DAILY_ORDER_LIMIT": "1æ—¥æ³¨æ–‡ä¸Šé™",
    "HOLDING_DATA_REQUIRED": "ä¿æœ‰æ ªæ•°æœªè¨­å®š",
    "SHARES_UNAVAILABLE": "æ ªæ•°æœªè¨­å®š",
    "SHARES_RULE_UNSUPPORTED": "æ ªæ•°ãƒ«ãƒ¼ãƒ«æœªå¯¾å¿œ",
    "FX_PLANNING_RATE_REQUIRED": "ç‚ºæ›¿ãƒ¬ãƒ¼ãƒˆæœªè¨­å®š",
    "STRATEGY_NOT_ACTIVE": "æˆ¦ç•¥åœæ­¢ä¸­",
    "EXECUTION_RECONCILIATION_REQUIRED": "ç´„å®šç…§åˆãŒå¿…è¦",
    "ACCOUNT_TRANSFER_REQUIRED": "è£œå®Œè³‡é‡‘ã®å…¥é‡‘å¾…ã¡",
    "ACCOUNT_TAXABLE_GIFTS_YTD_REQUIRED": "è³‡é‡‘ç§»ç®¡ç´¯è¨ˆæœªè¨­å®š",
    "GIFT_TAX_REVIEW_REQUIRED": "è³‡é‡‘ç§»ç®¡ã®ç¨Žå‹™ç¢ºèª",
    "CONCENTRATION_AUDIT_REQUIRED": "ä¸–å¸¯é›†ä¸­åº¦ç›£æŸ»å¾…ã¡",
    "CONCENTRATION_HARD_LIMIT": "ä¸–å¸¯é›†ä¸­åº¦ä¸Šé™è¶…éŽ",
    "CONCENTRATION_WARNING": "ä¸–å¸¯é›†ä¸­åº¦æ³¨æ„",
    "EARNINGS_AUDIT_REQUIRED": "HOSæ±ºç®—ç›£æŸ»å¾…ã¡",
    "EARNINGS_NEUTRAL": "æ±ºç®—æ§˜å­è¦‹",
    "EARNINGS_NEGATIVE": "æ±ºç®—æ‚ªåŒ–ãƒ»è³¼å…¥åœæ­¢",
    "FIXED_LIMIT_REQUIRED": "å›ºå®šæŒ‡å€¤æœªè¨­å®š",
    "MANUAL_STEP_SHARES_REQUIRED": "Stepæ ªæ•°æœªç¢ºå®š",
    "MULTIPLE_REGISTERED_PLANS": "åŒä¸€éŠ˜æŸ„ã®ç™»éŒ²è¨ˆç”»ãŒè¤‡æ•°",
    "PURCHASE_AUTHORITY_INVALID": "ç™»éŒ²æˆ¦ç•¥Authorityä¸å‚™",
    "FY_DECISION_NOT_ACTIVE": "å½“å¹´åº¦è³¼å…¥è¨ˆç”»å¤–",
}
USER_ACTION_BLOCKS = {
    "ACCOUNT_BUDGET_SECRET_REQUIRED",
    "ACCOUNT_BUYING_POWER_REQUIRED",
    "ACCOUNT_BUYING_POWER_INSUFFICIENT",
    "ACCOUNT_TRANSFER_REQUIRED",
    "ACCOUNT_TAXABLE_GIFTS_YTD_REQUIRED",
    "GIFT_TAX_REVIEW_REQUIRED",
}


def _money(value: float | None, currency: str = "JPY") -> str:
    if value is None:
        return "æœªå–å¾—"
    return f"${value:,.2f}" if currency == "USD" else f"Â¥{value:,.0f}"


def _compact_yen(value: float | None) -> str:
    if value is None:
        return "æœªè¨­å®š"
    if value >= 100_000_000 and value % 100_000_000 == 0:
        return f"{value / 100_000_000:,.0f}å„„å††"
    if value >= 10_000:
        return f"{value / 10_000:,.1f}ä¸‡å††".replace(".0ä¸‡å††", "ä¸‡å††")
    return f"{value:,.0f}å††"


def _percent(current: float | None, target: float | None) -> str | None:
    if current is None or target is None or target <= 0:
        return None
    return f"{current / target * 100:.1f}%"


def _shares(signal: Any) -> str:
    shares = getattr(signal, "shares", None)
    return f"{shares}æ ª" if shares is not None else str(getattr(signal, "shares_rule", None) or "æ ªæ•°æœªç¢ºå®š")


def _active_account_counts(signals: Iterable[Any]) -> dict[str, int]:
    tickers: dict[str, set[str]] = defaultdict(set)
    for signal in signals:
        if getattr(signal, "fy2026_decision", None) not in ACTIVE_FY_DECISIONS:
            continue
        account = str(getattr(signal, "account", "") or "")
        ticker = str(getattr(signal, "ticker", "") or "")
        if account and ticker:
            tickers[account].add(ticker)
    return {account: len(items) for account, items in tickers.items()}


def _unique_relevant(signals: Iterable[Any], account: str) -> list[Any]:
    rows = [row for row in signals if getattr(row, "account", None) == account and getattr(row, "status", None) in RELEVANT_STATUSES]
    rows.sort(key=lambda row: (STATUS_RANK.get(getattr(row, "status", ""), 9), int(getattr(row, "execution_priority", 99)), float(getattr(row, "distance_to_limit_percent", 999) or 999), int(getattr(row, "step_index", 99))))
    unique: dict[str, Any] = {}
    for row in rows:
        unique.setdefault(str(getattr(row, "ticker", "")), row)
    return list(unique.values())


def _translated_blocks(blocks: Iterable[str]) -> list[str]:
    translated: list[str] = []
    for block in blocks:
        label = BLOCK_LABELS.get(str(block).split(":", 1)[0], "HOSç›£æŸ»å¾…ã¡")
        if label not in translated:
            translated.append(label)
    return translated


def _strategy_summary(signals: list[Any], account_labels: Mapping[str, str], per_account_limit: int = 3) -> list[str]:
    counts = _active_account_counts(signals)
    lines: list[str] = []
    for account in sorted(counts):
        lines.append(f"ã€{account_labels.get(account, account)}ã€‘")
        relevant = _unique_relevant(signals, account)
        if not relevant:
            lines.append(f"ãƒ»è©²å½“ãªã—ï¼ˆç›£è¦– {counts[account]}éŠ˜æŸ„ï¼‰")
            continue
        for signal in relevant[:per_account_limit]:
            status = str(getattr(signal, "status", ""))
            lines.append(f"{STATUS_LABELS.get(status, 'ãƒ»ç¢ºèª')} {getattr(signal, 'ticker', '')} {getattr(signal, 'name', '')}ï½œ{_money(getattr(signal, 'current_price', None), getattr(signal, 'currency', 'JPY'))} â†’ æŒ‡å€¤{_money(getattr(signal, 'limit_price', None), getattr(signal, 'currency', 'JPY'))}ï½œ{_shares(signal)}")
            raw_blocks = [str(block) for block in (getattr(signal, "blocks", []) or [])]
            hos_blocks = _translated_blocks(block for block in raw_blocks if block not in USER_ACTION_BLOCKS)
            user_blocks = _translated_blocks(block for block in raw_blocks if block in USER_ACTION_BLOCKS)
            if hos_blocks:
                lines.append(f"   HOSå´ï¼š{'ãƒ»'.join(hos_blocks[:3])}")
            if user_blocks:
                lines.append(f"   ãƒ¦ãƒ¼ã‚¶ãƒ¼å´ï¼š{'ãƒ»'.join(user_blocks[:3])}")
        if len(relevant) > per_account_limit:
            lines.append(f"ãƒ»ã»ã‹ {len(relevant) - per_account_limit}ä»¶")
    return lines


LOGIC_STATUS_RANK = {
    "LOGIC_PASS": 0,
    "BLOCKED": 1,
    "DAILY_LIMIT": 2,
    "NEAR": 3,
    "ABOVE_CEILING": 4,
    "DATA_ERROR": 5,
    "WAIT": 6,
}


def _logic_rows(candidates: Iterable[Any]) -> list[Any]:
    """Select private manual-logic rows without exposing account identifiers."""
    rows = [
        row for row in candidates
        if getattr(row, "status", None) in LOGIC_STATUS_RANK or getattr(row, "blocks", None)
    ]
    rows.sort(key=lambda row: (
        LOGIC_STATUS_RANK.get(str(getattr(row, "status", "")), 99),
        int(getattr(row, "execution_priority", 99) or 99),
        float(getattr(row, "distance_to_limit_percent", 999) or 999),
        str(getattr(row, "ticker", "")),
        int(getattr(row, "step_index", 99) or 99),
    ))
    unique: dict[str, Any] = {}
    for row in rows:
        unique.setdefault(str(getattr(row, "ticker", "")), row)
    return list(unique.values())


def _logic_summary(candidates: Iterable[Any], per_limit: int = 3) -> list[str]:
    """Render a manual-review panel that can never be read as order approval."""
    relevant = _logic_rows(candidates)
    passes = [row for row in relevant if getattr(row, "status", None) == "LOGIC_PASS"]
    lines = ["ã€éŠ˜æŸ„ãƒ­ã‚¸ãƒƒã‚¯ï¼ˆæ‰‹å‹•åˆ¤æ–­ç”¨ï¼‰ã€‘", f"ðŸŸ¢ é€šéŽ {len(passes)}ä»¶ï¼ˆHOSã®ç™ºæ³¨å¯ã§ã¯ãªã»ç­m¢G§²ÚîÆ­yÖöv–5ööæÇ’‚“ ¢6÷W&6Uö–BÒ&ÆVv7•öÇ† ¢&öf–ÆRÒÆöE÷&—fFU÷&öf–ÆR‡°¢$„õ5õ$•dDUõ$ôd”ÄUô¥4ôâ#¢§6öâæGV×2‡²&66÷VçG2#¢²&ÆVv7•övÖÖ#¢·×ÒÂ&†öÆF–æw2#¢µ×Ò’À¢$„õ5õ$•dDUõ5E$DTu•ô¥4ôâ#¢§6öâæGV×2‡°¢'fW'6–öâ#¢À¢'6÷W&6Uö66÷VçEö–G2#¢·6÷W&6Uö–EÒÀ¢'7G&FVw’#¢°¢'7G&FVw•ö–B#¢%$•dDUõ4õU$4UõÄâ"À¢'7FGW2#¢$5D•dR"À¢'W&6†6UöWF†÷&—G’#¢²&ÖöFR#¢%$Tt•5DU$TEõ5E$DTu•ôôäÅ’"Â&WFõö÷&FW"#¢fÇ6RÂ&WFõ÷6VÆÂ#¢fÇ6WÒÀ¢&66÷VçG2#¢·6÷W&6Uö–C¢²&÷&FW'2#¢µ××ÒÀ¢ÒÀ¢Ò’À¢Ò ¢ÖçVÂÒÆöE÷&—fFUöÖçVÅöÆöv–5÷7G&FVw’‡&öf–ÆRÂ°¢$„õ5õ$•dDUõ5E$DTu•ô¥4ôâ#¢§6öâæGV×2‡°¢'fW'6–öâ#¢À¢'6÷W&6Uö66÷VçEö–G2#¢·6÷W&6Uö–EÒÀ¢'7G&FVw’#¢°¢'7G&FVw•ö–B#¢%$•dDUõ4õU$4UõÄâ"À¢'7FGW2#¢$5D•dR"À¢'W&6†6UöWF†÷&—G’#¢²&ÖöFR#¢%$Tt•5DU$TEõ5E$DTu•ôôäÅ’"Â&WFõö÷&FW"#¢fÇ6RÂ&WFõ÷6VÆÂ#¢fÇ6WÒÀ¢&66÷VçG2#¢·6÷W&6Uö–C¢²&÷&FW'2#¢µ××ÒÀ¢ÒÀ¢Ò’À¢Ò ¢76W'B6WB†ÖçVÅ²&66÷VçG2%Ò’ÓÒ²&ÖVÖ&W%öÆöv–5ö'Ð¢76W'BÖçVÅ²'7G&FVw•ö–B%ÒÓÒ%$•dDUôÔåTÅôÄôt”2 ¢76W'B6÷W&6Uö–Bæ÷B–â§6öâæGV×2†ÖçVÂ¢76W'BÆöE÷&—fFU÷7G&FVw’‡&öf–ÆR•²'7FGW2%ÒÓÒ$E$eB   ¦FVbFW7E÷Væ&÷VæEöÖçVÅöÆöv–5÷&V¦V7G5öWFöÖF–5ö÷&FW%öWF†÷&—G’‚“ ¢&öf–ÆRÒ²%÷'VçF–ÖU÷&—fFU÷7G&FVw•ö–×÷'E÷7FFR#¢$44õTåEô$”äD”äuõ$UT•$TB'Ð¢ÖçVÂÒÆöE÷&—fFUöÖçVÅöÆöv–5÷7G&FVw’‡&öf–ÆRÂ°¢$„õ5õ$•dDUõ5E$DTu•ô¥4ôâ#¢§6öâæGV×2‡°¢'fW'6–öâ#¢À¢'6÷W&6Uö66÷VçEö–G2#¢²&ÆVv7•öÇ†%ÒÀ¢'7G&FVw’#¢°¢'7FGW2#¢$5D•dR"À¢'W&6†6UöWF†÷&—G’#¢²&ÖöFR#¢%$Tt•5DU$TEõ5E$DTu•ôôäÅ’"Â&WFõö÷&FW"#¢G'VRÂ&WFõ÷6VÆÂ#¢fÇ6WÒÀ¢&66÷VçG2#¢²&ÆVv7•öÇ†#¢²&÷&FW'2#¢µ××ÒÀ¢ÒÀ¢Ò’À¢Ò¢76W'BÖçVÂÓÒ·Ð  ¦FVbFW7E÷7G&FVw•ööæÇ•÷6V7&WEöæWfW%÷&WÆ6W5öåöW†—7F–æu÷&öf–ÆU÷7G&FVw’‚“ ¢W†—7F–ærÒVF—FVE÷7G&FVw’‚¢W†—7F–æu²'W&6†6UöWF†÷&—G’%ÒÒ°¢&ÖöFR#¢%$Tt•5DU$TEõ5E$DTu•ôôäÅ’"À¢&WFõö÷&FW"#¢fÇ6RÀ¢&WFõ÷6VÆÂ#¢fÇ6RÀ¢Ð¢&öf–ÆRÒÆöE÷&—fFU÷&öf–ÆR‡°¢$„õ5õ$•dDUõ$ôd”ÄUô¥4ôâ#¢§6öâæGV×2‡°¢&66÷VçG2#¢²&ÖVÖ&W%ö#¢·×ÒÀ¢'7G&FVw’#¢W†—7F–ærÀ¢Ò’À¢$„õ5õ$•dDUõ5E$DTu•ô¥4ôâ#¢§6öâæGV×2‡°¢'fW'6–öâ#¢À¢'6÷W&6Uö66÷VçEö–G2#¢²&ÆVv7•öÇ†%ÒÀ¢'7G&FVw’#¢°¢'7G&FVw•ö–B#¢$”Õõ%EôÕU5EôäõEõt”â"À¢'7FGW2#¢$5D•dR"À¢'W&6†6UöWF†÷&—G’#¢²&ÖöFR#¢%$Tt•5DU$TEõ5E$DTu•ôôäÅ’"Â&WFõö÷&FW"#¢fÇ6RÂ&WFõ÷6VÆÂ#¢fÇ6WÒÀ¢&66÷VçG2#¢²&ÆVv7•öÇ†#¢²&÷&FW'2#¢µ××ÒÀ¢ÒÀ¢Ò’À¢Ò ¢76W'B&öf–ÆU²'7G&FVw’%Õ²'7G&FVw•ö–B%ÒÓÒ%DU5Eõ$•dDUõ5E$DTu’ ¢76W'B%÷'VçF–ÖU÷&—fFU÷7G&FVw•ö–×÷'E÷7FFR"æ÷B–â&öf–ÆP  ¦FVböf—'7E÷6–væÂ†Vçb“ ¢7G&FVw’ÒVF—FVE÷7G&FVw’‚¢&–6RÒ&–6U&V6÷&B‚#"Â$W†×ÆR–æ6öÖR6ò"Â“RÂÂFFRçFöF’‚’Â&Öö6²"Â&ÖVF—VÒ"¢6–væÂÒWfÇVFU÷7G&FVw’‡7G&FVw’Â·&–6UÒÂVçcÖVçb•³Ð¢&WGW&âÇ•ö†÷W6V†öÆEögVæF–æuövFW2…·6–væÅÒÂ7G&FVw’ÂVçcÖVçb•³Ð  ¦FVbFW7EöW†—7F–æu÷÷6—F–öåö6ö×ÆWF–öåö6åö&U÷&VG•ööæÇ•ögFW%öÆÅögVæF–æuövFW2‚“ ¢6–væÂÒöf—'7E÷6–væÂ†&6UöVçb‚’¢76W'B6–væÂæ7F–öæ&–Æ—G’ÓÒ%$TE’ ¢76W'B6–væÂçW&6†6UöfÆrÓÒ%U$4„4Uõ$TE’   ¦FVbFW7Eö6ö×ÆWF–öåö—5ö&Æö6¶VE÷VçF–Å÷G&ç6fW%öÆæG2‚“ ¢VçbÒ&6UöVçb‚¢Vçe²$„õ5ô44õTåEôÔTÔ$U%ôô%U””äuõõtU%ô¥’%ÒÒ# ¢6–væÂÒöf—'7E÷6–væÂ†Vçb¢76W'B6–væÂæ7F–öæ&–Æ—G’ÓÒ$E$eB ¢76W'B$44õTåEõE$å4dU%õ$UT•$TB"–â6–væÂæ&Æö6·0  ¦FVbFW7Eö6ö×ÆWF–öå÷7F÷5ö&÷fUöv–gE÷F…öwV&E÷VçF–Å÷&Wf–WvVB‚“ ¢VçbÒ&6UöVçb‚¢Vçe²$„õ5ô44õTåEôÔTÔ$U%ôõD„$ÄUôt”eE5õ•DEô¥’%ÒÒ## ¢76W'B$t”eEõD…õ$Ud”Uuõ$UT•$TB"–âöf—'7E÷6–væÂ†Vçb’æ&Æö6·0¢Vçe²$„õ5ô44õTåEôÔTÔ$U%ôôt”eEõD…õ$Ud”UtTB%ÒÒ'G'VR ¢76W'B$t”eEõD…õ$Ud”Uuõ$UT•$TB"æ÷B–âöf—'7E÷6–væÂ†Vçb’æ&Æö6·0  ¦FVbFW7Eö66…öfÆö÷%ö&Æö6·5÷v†Vå÷fW&–f–VEö&æµö66…ö—5ö&VÆ÷uöfÆö÷"‚“ ¢VçbÒ&6UöVçb‚¢Vçe²$„õ5ô5U%$TåEô„õU4T„ôÄEô44…ô¥’%ÒÒ#“““’ ¢6–væÂÒöf—'7E÷6–væÂ†Vçb¢76W'B6–væÂæ7F–öæ&–Æ—G’ÓÒ$E$eB ¢76W'B%$õDT5DTEô44…ôdÄôõ%ô%$T4‚"–â6–væÂæ&Æö6·0  ¦FVbFW7Eö66…öEöfÆö÷%öFöW5öæ÷EöF÷V&ÆUö6÷VçEö÷&FW%öv–ç7Eö&æµö66‚‚“ ¢VçbÒ&6UöVçb‚¢Vçe²$„õ5ô5U%$TåEô„õU4T„ôÄEô44…ô¥’%ÒÒ# ¢76W'B%$õDT5DTEô44…ôdÄôõ%ô%$T4‚"æ÷B–âöf—'7E÷6–væÂ†Vçb’æ&Æö6·0