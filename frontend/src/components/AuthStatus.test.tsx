import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthStatus } from "./AuthStatus";

describe("AuthStatus (Phase 10.2)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a login link when not authenticated", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(JSON.stringify({ authenticated: false }), { status: 200 }),
    );
    render(<AuthStatus />);
    await waitFor(() => expect(screen.getByText("登入")).toBeInTheDocument());
  });

  it("shows the display name and a logout button when authenticated", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          authenticated: true,
          subject: "abc",
          issuer: "https://idp.example",
          display_name: "Alice",
          permissions: ["review.accept", "review.reject"],
        }),
        { status: 200 },
      ),
    );
    render(<AuthStatus />);
    await waitFor(() => expect(screen.getByText("Alice")).toBeInTheDocument());
    expect(screen.getByText("登出")).toBeInTheDocument();
    expect(screen.queryByText("（無審核權限）")).not.toBeInTheDocument();
  });

  it("shows a no-review-permission note for a user without any review.* permission", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          authenticated: true,
          subject: "abc",
          issuer: "https://idp.example",
          display_name: "Bob",
          permissions: ["image.analyze", "image.redact", "image.verify"],
        }),
        { status: 200 },
      ),
    );
    render(<AuthStatus />);
    await waitFor(() => expect(screen.getByText("（無審核權限）")).toBeInTheDocument());
  });

  it("treats a 404 (OIDC not configured) the same as not authenticated", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(new Response("", { status: 404 }));
    render(<AuthStatus />);
    await waitFor(() => expect(screen.getByText("登入")).toBeInTheDocument());
  });

  it("never renders a token, session id, or client secret", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(JSON.stringify({ authenticated: true, subject: "abc", issuer: "https://idp.example" }), { status: 200 }),
    );
    const { container } = render(<AuthStatus />);
    await waitFor(() => expect(screen.getByText("登出")).toBeInTheDocument());
    const html = container.innerHTML.toLowerCase();
    for (const forbidden of ["token", "secret", "session_id", "mg_sess"]) {
      expect(html).not.toContain(forbidden);
    }
  });

  it("clicking logout posts to the logout endpoint and reverts to the login link", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ authenticated: true, subject: "abc", issuer: "https://idp.example", display_name: "Alice" }), {
        status: 200,
      }),
    );
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ status: "logged_out" }), { status: 200 }));

    render(<AuthStatus />);
    await waitFor(() => expect(screen.getByText("登出")).toBeInTheDocument());

    await userEvent.click(screen.getByText("登出"));

    await waitFor(() => expect(screen.getByText("登入")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenLastCalledWith(expect.stringContaining("/api/v1/auth/logout"), expect.objectContaining({ method: "POST" }));
  });
});
