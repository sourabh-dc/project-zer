'use client';
import { ButtonHTMLAttributes } from 'react';
import { clsx } from 'clsx';

export function Button({
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={clsx(
        'inline-flex items-center justify-center rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50',
        className,
      )}
    />
  );
}



