import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CurrentUser } from "../lib/types";
import { renderWithPreferences } from "../test/render";
import { RoleGate } from "./RoleGate";

const user = (role: CurrentUser["role"]): CurrentUser => ({
  subject: `test-${role}`,
  display_name: "Test User",
  role,
  auth_mode: "dev",
});

describe("RoleGate", () => {
  it("blocks an observer from engineering", () => {
    renderWithPreferences(
      <RoleGate user={user("observer")} allowed={["instrument_engineer"]}>
        <span>protected content</span>
      </RoleGate>,
    );
    expect(screen.getByText("此工作区受权限保护")).toBeInTheDocument();
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });

  it("allows an administrator through every gate", () => {
    renderWithPreferences(
      <RoleGate user={user("administrator")} allowed={["instrument_engineer"]}>
        <span>protected content</span>
      </RoleGate>,
    );
    expect(screen.getByText("protected content")).toBeInTheDocument();
  });
});
