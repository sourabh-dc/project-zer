"use client";
import { ReactNode } from "react";
import { useSession } from "@/lib/useSession";

export default function AuthGate({ children, permission }: { children: ReactNode; permission?: string }) {
  const { data, isLoading } = useSession();
  if (isLoading) return <p className="p-4 text-gray-600">Loading session…</p>;
  if (!data?.authenticated) return <p className="p-4 text-red-600">Please sign in.</p>;
  if (permission && !((data?.claims?.permissions || []).includes("*") || (data?.claims?.permissions || []).includes(permission))) {
    return <p className="p-4 text-red-600">You do not have permission to view this page.</p>;
  }
  return <>{children}</>;
}


