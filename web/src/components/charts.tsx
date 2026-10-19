"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { compact, money } from "./ui";

const INDIGO = "#4f46e5";
const AXIS = { fontSize: 11, fill: "#64748b" };

type Row = Record<string, string | number | boolean | null>;

export function TrendChart({ data, x, y, height = 260 }: { data: Row[]; x: string; y: string; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="#e2e8f0" vertical={false} />
        <XAxis dataKey={x} tick={AXIS} tickLine={false} axisLine={false} minTickGap={24} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} tickFormatter={(v: number) => compact(v)} width={48} />
        <Tooltip formatter={(v) => money(Number(v))} />
        <Line type="monotone" dataKey={y} stroke={INDIGO} strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function RankChart({ data, x, y, height = 260 }: { data: Row[]; x: string; y: string; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="#e2e8f0" horizontal={false} />
        <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} tickFormatter={(v: number) => compact(v)} />
        <YAxis type="category" dataKey={x} tick={AXIS} tickLine={false} axisLine={false} width={110} />
        <Tooltip formatter={(v) => money(Number(v))} />
        <Bar dataKey={y} fill={INDIGO} radius={[0, 4, 4, 0]} barSize={16} />
      </BarChart>
    </ResponsiveContainer>
  );
}
