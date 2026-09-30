"use client";

import { useEffect, useRef, useState } from "react";

import { authenticate, type DemoUser } from "@/lib/auth";

type LoginModalProps = {
  isOpen: boolean;
  onClose: () => void;
  onLoggedIn: (user: DemoUser) => void;
};

export default function LoginModal({ isOpen, onClose, onLoggedIn }: LoginModalProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const usernameRef = useRef<HTMLInputElement>(null);

  // Fresh, empty form on every open; nothing about a previous attempt should
  // survive a close.
  useEffect(() => {
    if (!isOpen) {
      return;
    }

    setUsername("");
    setPassword("");
    setError(null);
    usernameRef.current?.focus();
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const user = authenticate(username, password);
    if (!user) {
      setError("Incorrect username or password.");
      return;
    }

    onLoggedIn(user);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 px-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="login-modal-title"
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-sm overflow-hidden rounded-2xl border border-violet-200 bg-white shadow-[0_18px_40px_rgba(17,17,17,0.24)]"
      >
        <header className="flex items-center justify-between border-b border-violet-100 px-5 py-3">
          <h2 id="login-modal-title" className="text-sm font-semibold tracking-wide text-violet-900">
            Log in / Sign up
          </h2>
          <button
            type="button"
            aria-label="Close log in"
            onClick={onClose}
            className="inline-flex h-8 w-8 items-center justify-center rounded-full text-black/70 transition-colors hover:bg-violet-50 hover:text-black"
          >
            <span aria-hidden className="text-xl leading-none">
              ×
            </span>
          </button>
        </header>

        <form onSubmit={submit} className="space-y-4 px-5 py-5">
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-black/55">
              Username
            </span>
            <input
              ref={usernameRef}
              type="text"
              autoComplete="username"
              value={username}
              onChange={(event) => {
                setUsername(event.target.value);
                setError(null);
              }}
              placeholder="Your username"
              className="h-10 w-full rounded-xl border border-violet-200 px-3 text-sm outline-none transition-colors focus:border-violet-600"
            />
          </label>

          <label className="block">
            <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-black/55">
              Password
            </span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                setError(null);
              }}
              placeholder="Your password"
              className="h-10 w-full rounded-xl border border-violet-200 px-3 text-sm outline-none transition-colors focus:border-violet-600"
            />
          </label>

          {error ? (
            <p role="alert" className="text-xs font-medium text-rose-600">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            className="h-10 w-full rounded-full bg-violet-700 text-sm font-semibold text-white transition-colors hover:bg-violet-800"
          >
            Log in
          </button>
        </form>
      </div>
    </div>
  );
}
