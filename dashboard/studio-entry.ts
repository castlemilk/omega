/** Both dashboard builds hand the browser the same unscoped Studio entry. */
export function businessStudioCommand(origin: string | undefined): string | null {
  if (!origin) return null;
  if (/^https:\/\/[^\s/?#@\\]+\/?$/i.test(origin)) {
    try {
      return new URL("/command", origin).href;
    } catch {
      // Report the setting name without printing the supplied value.
    }
  }
  throw new Error("OMEGA_BUSINESS_STUDIO_ORIGIN must be a bare HTTPS origin.");
}
