'use client';

import Link from 'next/link';
import Image from 'next/image';
import { usePathname } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Moon, Sun, LogOut } from 'lucide-react';
import { useTheme } from 'next-themes';
import { useEffect, useState, useTransition } from 'react';
import { useAuth } from '@/contexts/auth-context';
import { useOnboarding } from '@/contexts/onboarding-context';

export function Navbar() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const [, startTransition] = useTransition();
  const { user, isAuthenticated, loading, logout } = useAuth();
  const { state: onboarding } = useOnboarding();
  const showNewJobDot = onboarding.resumeSaved && !onboarding.firstJobCreated && !onboarding.completed;

  // Standard next-themes pattern: set mounted after client-side hydration
  useEffect(() => {
    startTransition(() => {
      setMounted(true);
    });
  }, [startTransition]);

  // Authenticated navigation links
  const authNavLinks = [
    { href: '/', label: 'Home' },
    { href: '/settings', label: 'Settings' },
    { href: '/jobs', label: 'Jobs' },
    { href: '/jobs/new', label: 'New Job' },
  ];

  // Unauthenticated: only Home and Login
  const publicNavLinks = [
    { href: '/', label: 'Home' },
  ];

  const navLinks = isAuthenticated ? authNavLinks : publicNavLinks;

  return (
    <nav className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto px-4">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <Link href="/" className="flex items-center space-x-2">
            <span className="text-xl font-bold">TailorTom</span>
          </Link>

          {/* Navigation Links */}
          <div className="hidden md:flex items-center space-x-6">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={`relative text-sm font-medium transition-colors hover:text-primary ${
                  pathname === link.href
                    ? 'text-foreground'
                    : 'text-muted-foreground'
                }`}
              >
                {link.label}
                {showNewJobDot && link.href === '/jobs/new' && (
                  <span className="absolute -top-1 -right-2.5 flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
                  </span>
                )}
              </Link>
            ))}
          </div>

          {/* Right side: Theme toggle + Auth */}
          <div className="flex items-center space-x-3">
            {/* Theme Toggle */}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              aria-label="Toggle theme"
            >
              {mounted ? (
                theme === 'dark' ? (
                  <Sun className="h-5 w-5" />
                ) : (
                  <Moon className="h-5 w-5" />
                )
              ) : (
                <Moon className="h-5 w-5" />
              )}
            </Button>

            {/* Auth section */}
            {!loading && (
              isAuthenticated && user ? (
                <div className="flex items-center space-x-3">
                  {/* Avatar */}
                  {user.avatar_url ? (
                    <Image
                      src={user.avatar_url}
                      alt={user.name || user.email}
                      width={32}
                      height={32}
                      className="rounded-full"
                      referrerPolicy="no-referrer"
                    />
                  ) : (
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground text-sm font-medium">
                      {(user.first_name?.[0] || user.email[0]).toUpperCase()}
                    </div>
                  )}

                  {/* Logout */}
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={logout}
                    aria-label="Sign out"
                    title="Sign out"
                  >
                    <LogOut className="h-4 w-4" />
                  </Button>
                </div>
              ) : (
                <Link href="/login">
                  <Button variant="default" size="sm">
                    Sign in
                  </Button>
                </Link>
              )
            )}
          </div>
        </div>

        {/* Mobile Navigation */}
        <div className="md:hidden pb-4">
          <div className="flex flex-col space-y-2">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={`text-sm font-medium transition-colors hover:text-primary ${
                  pathname === link.href
                    ? 'text-foreground'
                    : 'text-muted-foreground'
                }`}
              >
                {link.label}
              </Link>
            ))}
          </div>
        </div>
      </div>
    </nav>
  );
}
