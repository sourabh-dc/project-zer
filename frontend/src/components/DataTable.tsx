'use client';
import { ReactNode } from 'react';

export function DataTable<T>({
  columns,
  rows,
  empty,
}: {
  columns: {
    key: keyof T;
    header: string;
    render?: (value: any, row: T) => ReactNode;
  }[];
  rows: T[];
  empty?: ReactNode;
}) {
  if (!rows?.length)
    return (
      <div className="rounded border bg-white p-6 text-gray-600">
        {empty || 'No data'}
      </div>
    );
  return (
    <div className="overflow-x-auto rounded border bg-white">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            {columns.map((c) => (
              <th
                key={String(c.key)}
                className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 bg-white">
          {rows.map((row, i) => (
            <tr key={i} className="hover:bg-gray-50">
              {columns.map((c) => (
                <td
                  key={String(c.key)}
                  className="whitespace-nowrap px-4 py-2 text-sm text-gray-900"
                >
                  {c.render
                    ? c.render((row as any)[c.key], row)
                    : String((row as any)[c.key] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}



