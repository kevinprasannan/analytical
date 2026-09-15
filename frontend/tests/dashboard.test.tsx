import { screen } from "@testing-library/react";
import { renderApp } from "./render";
import { Dashboard } from "@/features/dashboard/Dashboard";

test("renders a score row from the API", async () => {
  renderApp(<Dashboard />, { route: "/dashboard?tf=M15" });
  expect(await screen.findByText("NIFTY-FUT-2026-09")).toBeInTheDocument();
  expect(await screen.findByText("42.5")).toBeInTheDocument();
  expect(screen.getByText("Bullish")).toBeInTheDocument();
});

test("shows the worker-idle banner when worker_running is false", async () => {
  renderApp(<Dashboard />, { route: "/dashboard?tf=M15" });
  expect(await screen.findByText(/Worker not running/i)).toBeInTheDocument();
});
