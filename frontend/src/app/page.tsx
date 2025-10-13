export default function Home() {
  return (
    <main className="mx-auto max-w-5xl p-8">
      <h1 className="text-3xl font-semibold">ZeroQue Frontend</h1>
      <p className="mt-2 text-gray-600">Choose a portal to begin:</p>
      <ul className="mt-6 list-disc pl-6 space-y-2">
        <li>
          <a className="text-blue-600 underline" href="/admin">Admin Console</a>
        </li>
        <li>
          <a className="text-blue-600 underline" href="/merchant">Merchant Portal</a>
        </li>
        <li>
          <a className="text-blue-600 underline" href="/app">End-Customer App</a>
        </li>
      </ul>
    </main>
  );
}


