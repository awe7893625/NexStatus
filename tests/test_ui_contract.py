from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HammerspoonUIContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (ROOT / "hammerspoon" / "nexstatus.lua").read_text()
        cls.native_source = (ROOT / "native" / "NexStatusMenuBar.swift").read_text()

    def test_native_click_opens_original_panel_through_local_notification(self) -> None:
        self.assertIn("DistributedNotificationCenter.default()", self.native_source)
        self.assertNotIn("NSPopover", self.native_source)
        self.assertNotIn("hammerspoon://nexstatus", self.native_source)
        self.assertIn('hs.distributednotifications.new(function()', self.source)
        self.assertGreaterEqual(self.source.count("com.nexstatus.open-panel"), 1)
        self.assertGreaterEqual(self.source.count("M._nativeOpenObserver:stop()"), 2)

    def test_panel_click_is_served_from_prebuilt_cache(self) -> None:
        self.assertIn("cachedPanelHtml", self.source)
        self.assertIn("prefsFingerprint", self.source)
        self.assertIn("needsRebuild", self.source)

    def test_token_ledger_is_the_primary_dashboard_section(self) -> None:
        self.assertIn('class="ledger-overview"', self.source)
        self.assertIn('NexStatus<span>成本中心</span>', self.source)
        self.assertIn("Token 使用研究", self.source)
        self.assertIn('data-window-target="today"', self.source)
        self.assertIn('data-window="today"', self.source)
        self.assertIn("台北 00:00 起", self.source)
        self.assertIn("今日各平台 Token 長條圖", self.source)
        self.assertIn("todaySourceBarHTML", self.source)
        self.assertIn('{ id="grok", label="Grok", class="grok-line" }', self.source)
        self.assertIn('{ id="openrouter", label="OpenRouter", class="openrouter-line" }', self.source)
        self.assertIn('openrouter = { label = "OpenRouter", accent = "#0A84FF" }', self.source)
        self.assertIn('"OpenRouter · " .. tostring(seatName)', self.source)
        self.assertIn('for _, seatName in ipairs({ "dsh", "global" }) do', self.source)
        self.assertIn('key 月 " .. keyUsage .. " / " .. keyLimit', self.source)
        self.assertIn('帳號餘額低於 20%', self.source)
        self.assertIn('accent = lowBalance and "#FF453A" or "#0A84FF"', self.source)
        self.assertIn('deltaMoney(seat.delta_today)', self.source)
        self.assertIn('deltaMoney(seat.delta_7d)', self.source)
        self.assertIn("top-one-line", self.source)
        self.assertIn("近 3 日", self.source)
        self.assertIn("近 7 日", self.source)
        self.assertIn("近 30 日", self.source)
        self.assertIn("本地算力", self.source)

    def test_openrouter_render_reference_is_inside_build_html_scope(self) -> None:
        build_block = self.source.split("buildHTML = function(s)", 1)[1].split(
            "\nlocal function positionPanel", 1
        )[0]
        self.assertIn("local openrouter = s.openrouter or {}", build_block)
        self.assertIn("buildOpenRouterSeat(seatName, openrouter[seatName])", build_block)

    def test_appearance_controls_are_progressively_disclosed(self) -> None:
        self.assertIn('<details class="appearance">', self.source)
        self.assertIn("aria-label", self.source)

    def test_accessibility_preferences_have_fallbacks(self) -> None:
        self.assertIn("prefers-reduced-motion: reduce", self.source)
        self.assertIn("prefers-reduced-transparency: reduce", self.source)

    def test_collector_refresh_is_async_single_flight_with_watchdog(self) -> None:
        self.assertIn("hs.task.new(PYTHON", self.source)
        self.assertIn("refreshQueued", self.source)
        self.assertIn("collectorWatchdog = hs.timer.doAfter(8", self.source)
        self.assertNotIn("hs.execute(cmd, true)", self.source)

    def test_ledger_opens_an_accessible_detail_sheet(self) -> None:
        self.assertIn('id="ledger-sheet"', self.source)
        self.assertIn('role="dialog" aria-modal="true"', self.source)
        self.assertIn('data-sheet-open="%s"', self.source)
        self.assertIn('class="ledger-overview token-overview" data-sheet-open="ledger"', self.source)
        self.assertIn("點擊任意空白處查看完整明細", self.source)
        self.assertIn("Token 使用分析", self.source)
        self.assertIn("各平台 Token", self.source)
        self.assertIn("各專案 Token", self.source)
        self.assertIn('data-window="30d"', self.source)
        self.assertIn('e.key === "Escape"', self.source)

    def test_background_poll_does_not_replace_interactive_webview(self) -> None:
        refresh_body = self.source.split("function M.refresh()", 1)[1].split("function M.start()", 1)[0]
        self.assertNotIn("panel:html(buildHTML", refresh_body)

    def test_provider_usage_cards_show_reset_date_and_countdown(self) -> None:
        self.assertIn('data-sheet-open="usage-%s"', self.source)
        self.assertIn("Claude Usage", self.source)
        self.assertIn("Codex Usage", self.source)
        self.assertIn("OpenCode Go Usage", self.source)
        self.assertIn("Grok Usage", self.source)
        self.assertIn("本週 credits", self.source)
        self.assertIn("月 credits", self.source)
        self.assertIn("Antigravity Usage", self.source)
        self.assertIn("fmtResetFull", self.source)
        self.assertIn("（台北）", self.source)
        self.assertIn("重置時間", self.source)

    def test_grok_seat_surfaces_false_available_lock(self) -> None:
        """Billing-vs-chat mismatch must render as 帳務鎖 / 假有額, not 0% green."""
        self.assertIn("false_available", self.source)
        self.assertIn("chat_gate", self.source)
        self.assertIn("帳務鎖", self.source)
        self.assertIn("假有額", self.source)
        self.assertIn("buildGrokSeatData", self.source)

    def test_grok_soft_limit_badge_when_api_omits_monthly_pool(self) -> None:
        """When API monthlyLimit=0, UI must badge 軟估 / 月估 (not blank —)."""
        self.assertIn("limit_missing", self.source)
        self.assertIn("limit_source", self.source)
        self.assertIn("軟估", self.source)
        self.assertIn("月估", self.source)
        self.assertIn("月 credits（軟估）", self.source)

    def test_mac_card_opens_host_resource_sheet_with_process_lists(self) -> None:
        self.assertIn("macHostSheetHTML", self.source)
        self.assertIn('id="usage-mac-sheet"', self.source)
        self.assertIn("Mac 資源", self.source)
        self.assertIn("誰在吃記憶體", self.source)
        self.assertIn("誰在吃 CPU", self.source)
        self.assertIn("分類加總", self.source)
        self.assertIn("top_mem_name", self.source)
        # Mac card always surfaces Swap (main line + dedicated bar).
        self.assertIn("Swap", self.source)
        self.assertIn('label = "Swap"', self.source)
        self.assertIn("swap_pct", self.source)
        # Mac card must open the sheet (not usage_sheet=false)
        self.assertNotIn("usage_sheet = false", self.source)

    def test_secondary_sections_are_reorderable_with_pointer_and_button_fallbacks(self) -> None:
        self.assertIn('data-section-id="%s" draggable="false"', self.source)
        self.assertIn("normalizedSectionOrder", self.source)
        self.assertIn('action:match("^order:([a-z_,]+)$")', self.source)
        self.assertIn("order-soft:", self.source)
        self.assertIn("layoutReorderSheetHTML", self.source)
        self.assertIn('id="layout-sheet"', self.source)
        self.assertIn('data-sheet-open="layout"', self.source)

    def test_each_card_tile_is_independently_reorderable(self) -> None:
        self.assertIn("sort-list", self.source)
        self.assertIn("sort-row", self.source)
        self.assertIn("sort-grip", self.source)
        self.assertIn("layout-nav-done", self.source)
        self.assertIn("編輯排序", self.source)
        self.assertIn('data-sort-list="%s"', self.source)
        self.assertIn('sortListHTML("providers"', self.source)
        self.assertIn('sortListHTML("token_sources"', self.source)
        self.assertIn('sortListHTML("token_kpis"', self.source)
        self.assertIn('sortListHTML("sections"', self.source)
        self.assertIn("normalizedTileOrder", self.source)
        self.assertIn('action:match("^tiles:([a-z_]+):([a-z0-9_,]+)$")', self.source)
        self.assertIn("tiles-soft:", self.source)
        self.assertIn("token_kpi_order", self.source)
        self.assertIn("token_source_order", self.source)
        self.assertIn("provider_order", self.source)
        self.assertIn("setupSortSheet", self.source)
        self.assertIn("layout-done", self.source)
        # Apple HIG reorder: grip control only, no up/down steppers in the list.
        self.assertNotIn("data-sort-dir", self.source)

    def test_layout_and_density_preferences_are_persisted_owner_only(self) -> None:
        self.assertIn('density = "comfortable"', self.source)
        self.assertIn('edit_layout = false', self.source)
        self.assertIn("section_order = normalizedSectionOrder", self.source)
        self.assertIn('chmod 700 %q', self.source)
        self.assertIn('chmod 600 %q', self.source)

    def test_glass_material_uses_large_continuous_corner_language(self) -> None:
        self.assertIn("border-radius: 30px", self.source)
        self.assertIn("border-radius: 28px", self.source)
        self.assertIn("backdrop-filter: blur(54px) saturate(180%%)", self.source)
        self.assertIn("cubic-bezier(.22,1,.36,1)", self.source)

    def test_compute_capacity_card_explains_free_local_and_combined_tokens(self) -> None:
        self.assertIn("免費雲端＋本地算力", self.source)
        self.assertIn("匿名 credential slot", self.source)
        self.assertIn("兩者合計", self.source)
        self.assertIn("compute-ratio", self.source)
        self.assertIn('data-sheet-open="%s"', self.source)
        self.assertIn('id="compute-sheet"', self.source)
        self.assertIn("credential slot", self.source)
        self.assertIn("資料覆蓋", self.source)
        self.assertIn('draggable="false"', self.source)
        self.assertIn('fixed = true', self.source)

    def test_each_anonymous_credential_slot_expands_to_sources_and_scenarios(self) -> None:
        self.assertIn('class="key-card"', self.source)
        self.assertIn("Credential Slot 與用途", self.source)
        self.assertIn("使用場景", self.source)
        self.assertIn("穩定匿名歸因單位", self.source)
        self.assertIn('sheetName + "-sheet"', self.source)

    def test_tokentracker_and_rag_cards_ui_contract(self) -> None:
        self.assertIn('name = "TokenTracker"', self.source)
        self.assertIn('name = "私有知識庫"', self.source)
        self.assertIn("compactNumber(today.tokens)", self.source)
        self.assertIn("compactNumber(r7d.tokens)", self.source)
        self.assertIn("local docs = rag.documents or {}", self.source)
        self.assertIn("docs.completed", self.source)
        self.assertIn("docs.queued", self.source)
        self.assertIn("docs.processing", self.source)
        self.assertGreaterEqual(self.source.count("static_card = true"), 2)
        self.assertNotIn("tt.error", self.source)
        self.assertNotIn("rag.error", self.source)

        card_section = self.source.split("local tt =")[1].split("local orderedProviders =")[0]
        self.assertNotIn("data-sheet-open", card_section)

        mac_card_block = self.source.split('id = "mac"', 1)[1].split("})", 1)[0]
        self.assertNotIn("static_card = true", mac_card_block)



class InstallerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (ROOT / "scripts" / "install.sh").read_text()

    def test_installer_does_not_interpolate_checkout_path_into_lua(self) -> None:
        self.assertIn('dofile(home .. "/.hammerspoon/nexstatus.lua")', self.source)
        self.assertNotIn('hs.setenv("NEXSTATUS_HOME", "${ROOT}")', self.source)
        self.assertNotIn('dofile("${LINK}")', self.source)

    def test_installer_refuses_symlinked_init_and_uses_owner_only_umask(self) -> None:
        self.assertIn('if [[ -L "${INIT}" ]]', self.source)
        self.assertIn("umask 077", self.source)
        self.assertIn('grep -qF -- "${MARKER_BEGIN}"', self.source)


class SecurityDocumentationContractTests(unittest.TestCase):
    def test_documentation_matches_persisted_snapshot_contract(self) -> None:
        source = (ROOT / "docs" / "SECURITY.md").read_text()
        self.assertIn("redacted operational metadata", source)
        self.assertIn("`0700`", source)
        self.assertIn("`0600`", source)
        self.assertNotIn("usage percentages and host metrics only", source)


if __name__ == "__main__":
    unittest.main()
