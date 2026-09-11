import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { Home } from "../pages/Home";
import { renderWithLanguage } from "../test/renderWithLanguage";

describe("LanguageSwitcher", () => {
  beforeEach(() => {
    // Each test's assumptions about the STARTING locale (default vs.
    // persisted-from-a-previous-test) must not depend on test execution
    // order — start every test from a clean slate.
    window.localStorage.clear();
  });

  it("defaults to Traditional Chinese", () => {
    renderWithLanguage(<Home />);
    expect(screen.getByText("MaskGuard — 圖片敏感資料防護")).toBeInTheDocument();
    expect(screen.getByText("開始分析")).toBeInTheDocument();
  });

  it("can start in English via the `locale` render option", () => {
    renderWithLanguage(<Home />, { locale: "en" });
    expect(screen.getByText("MaskGuard — Sensitive Data Protection for Images")).toBeInTheDocument();
    expect(screen.getByText("Start analysis")).toBeInTheDocument();
  });

  it("switching the selector re-renders every visible string in the new language, live", async () => {
    renderWithLanguage(<Home />);
    expect(screen.getByText("開始分析")).toBeInTheDocument();

    const select = screen.getByLabelText("Language / 語言");
    await userEvent.selectOptions(select, "en");

    expect(screen.getByText("Start analysis")).toBeInTheDocument();
    expect(screen.queryByText("開始分析")).not.toBeInTheDocument();
    expect(screen.getByText("MaskGuard — Sensitive Data Protection for Images")).toBeInTheDocument();

    await userEvent.selectOptions(select, "zh-TW");
    expect(screen.getByText("開始分析")).toBeInTheDocument();
    expect(screen.queryByText("Start analysis")).not.toBeInTheDocument();
  });

  it("persists the chosen language across a re-mount (localStorage)", async () => {
    const { unmount } = renderWithLanguage(<Home />);
    const select = screen.getByLabelText("Language / 語言");
    await userEvent.selectOptions(select, "en");
    expect(window.localStorage.getItem("maskguard.locale")).toBe("en");
    unmount();

    // A fresh mount with NO explicit `locale` option must pick up the
    // persisted choice rather than resetting to the zh-TW default.
    renderWithLanguage(<Home />);
    expect(screen.getByText("Start analysis")).toBeInTheDocument();
  });
});
