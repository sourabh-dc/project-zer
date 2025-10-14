"use client";
import { useState } from "react";

export default function LoginPage() {
  const [tenantId, setTenantId] = useState("");
  const [userId, setUserId] = useState("");
  const [tokenType, setTokenType] = useState<"guest" | "loyalty">("guest");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const body: any = { tenant_id: tenantId, token_type: tokenType };
      if (tokenType === "loyalty") body.user_id = userId;
      const res = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.error || "Login failed");
      window.location.href = "/";
    } catch (e: any) {
      setError(e?.message || "Unexpected error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-md p-8">
      <h1 className="text-2xl font-semibold">Login</h1>
      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <div>
          <label className="block text-sm text-gray-700">Tenant ID</label>
          <input className="mt-1 w-full rounded border px-3 py-2" value={tenantId} onChange={(e) => setTenantId(e.target.value)} required />
        </div>
        <div>
          <label className="block text-sm text-gray-700">Token Type</label>
          <select className="mt-1 w-full rounded border px-3 py-2" value={tokenType} onChange={(e) => setTokenType(e.target.value as any)}>
            <option value="guest">Guest</option>
            <option value="loyalty">Loyalty</option>
          </select>
        </div>
        {tokenType === "loyalty" && (
          <div>
            <label className="block text-sm text-gray-700">User ID</label>
            <input className="mt-1 w-full rounded border px-3 py-2" value={userId} onChange={(e) => setUserId(e.target.value)} required={tokenType === "loyalty"} />
          </div>
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button disabled={loading} className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50">{loading ? "Signing in..." : "Sign in"}</button>
      </form>
    </main>
  );
}


