import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Build a resume PDF filename as First_Last_resume.pdf (sanitized).
 * Use for admin downloads and anywhere a consistent resume filename is needed.
 */
export function resumePdfFilename(
  firstName: string | null | undefined,
  lastName: string | null | undefined,
): string {
  const first = (firstName || '').replace(/\W/g, '') || 'Unknown'
  const last = (lastName || '').replace(/\W/g, '') || 'Unknown'
  const f = first.charAt(0).toUpperCase() + first.slice(1).toLowerCase()
  const l = last.charAt(0).toUpperCase() + last.slice(1).toLowerCase()
  return `${f}_${l}_resume.pdf`
}
