import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AuthConfiguration } from "../lib/types";
import { renderWithPreferences } from "../test/render";
import { LoginPage } from "./LoginPage";

const configuration: AuthConfiguration = {
  auth_mode: "dev",
  default_account_id: "admin-id",
  accounts: [
    {
      id: "admin-id",
      username: "administrator",
      display_name: "Local Administrator",
      role: "administrator",
    },
    {
      id: "observer-id",
      username: "observer",
      display_name: "Local Observer",
      role: "observer",
    },
  ],
};

describe("LoginPage", () => {
  it("shows account choices without password fields and selects an account", () => {
    const onLogin = vi.fn(async () => undefined);
    renderWithPreferences(
      <LoginPage
        configuration={configuration}
        loading={false}
        busy={false}
        onLogin={onLogin}
      />,
    );

    expect(screen.getByRole("heading", { name: "选择本机账户登录" })).toBeInTheDocument();
    expect(screen.queryByLabelText(/密码/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Local Observer/ }));
    expect(onLogin).toHaveBeenCalledWith("observer-id");
  });
});
