import { createBrowserRouter, Navigate } from "react-router-dom";
import { Shell } from "@/components/layout/Shell";
import { Dashboard } from "@/features/dashboard/Dashboard";
import { InstrumentDetail } from "@/features/instrument-detail/InstrumentDetail";
import { InstrumentSeries } from "@/features/series/InstrumentSeries";
import { InstrumentRunsView } from "@/features/series/InstrumentRunsView";
import { InstrumentManager } from "@/features/instruments/InstrumentManager";
import { OptionChain } from "@/features/option-chain/OptionChain";
import { OiPulse } from "@/features/oi-pulse/OiPulse";
import { OiMovers } from "@/features/oi-movers/OiMovers";
import { PremiumDecay } from "@/features/premium-decay/PremiumDecay";
import { DailyDigest } from "@/features/daily-digest/DailyDigest";
import { Backtest } from "@/features/backtest/Backtest";
import { AstroStudy } from "@/features/astro/AstroStudy";
import { AstroDay } from "@/features/astro/AstroDay";
import { RunsList } from "@/features/runs/RunsList";
import { RunDetailView } from "@/features/runs/RunDetailView";
import { ConfigView } from "@/features/config/ConfigView";
import { CalendarView } from "@/features/calendar/CalendarView";
// The passcode gate (ShareGate) protects every URL; once unlocked the whole app
// is available.
const routes = [
  { index: true, element: <Navigate to="/dashboard" replace /> },
  { path: "dashboard", element: <Dashboard /> },
  { path: "instruments", element: <InstrumentManager /> },
  { path: "instruments/:id", element: <InstrumentDetail /> },
  { path: "instruments/:id/series", element: <InstrumentSeries /> },
  { path: "instruments/:id/runs", element: <InstrumentRunsView /> },
  { path: "instruments/:id/option-chain", element: <OptionChain /> },
  { path: "instruments/:id/oi-pulse", element: <OiPulse /> },
  { path: "instruments/:id/oi-movers", element: <OiMovers /> },
  { path: "instruments/:id/premium-decay", element: <PremiumDecay /> },
  { path: "instruments/:id/daily-digest", element: <DailyDigest /> },
  { path: "instruments/:id/backtest", element: <Backtest /> },
  { path: "runs", element: <RunsList /> },
  { path: "runs/:id", element: <RunDetailView /> },
  { path: "config", element: <ConfigView /> },
  { path: "calendar", element: <CalendarView /> },
  { path: "astro", element: <AstroStudy /> },
  { path: "astro/day/:date", element: <AstroDay /> },
  { path: "*", element: <Navigate to="/dashboard" replace /> },
];

export const router = createBrowserRouter([{ element: <Shell />, children: routes }]);
