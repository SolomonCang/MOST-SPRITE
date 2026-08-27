import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useI18n } from "../i18n/I18nProvider";
import { renderWithPreferences } from "../test/render";
import { PreferenceControls } from "./PreferenceControls";

function Probe() {
  const { t } = useI18n();
  return <><PreferenceControls /><h1>{t("observe.title")}</h1></>;
}

describe("PreferenceControls", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("switches the complete interface language and persists it", () => {
    renderWithPreferences(<Probe />);
    expect(screen.getByRole("heading", { name: "观测控制台" })).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("locale-en"));
    expect(screen.getByRole("heading", { name: "Observation workspace" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("en-US");
    expect(window.localStorage.getItem("most-sprite.locale")).toBe("en-US");
  });

  it("switches theme tokens without changing content", () => {
    renderWithPreferences(<Probe />);
    const initial = document.documentElement.dataset.theme;
    fireEvent.click(screen.getByTestId("theme-toggle"));
    expect(document.documentElement.dataset.theme).not.toBe(initial);
    expect(screen.getByRole("heading", { name: "观测控制台" })).toBeInTheDocument();
  });
});
