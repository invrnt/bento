import { describe, expect, it } from "vitest";

import { es } from "../../i18n/dictionary";
import { enOnboarding } from "../../i18n/en/onboarding";
import { esOnboarding } from "../../i18n/es/onboarding";

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();

describe("core-flows strings", () => {
  it("has an English translation for every Spanish key", () => {
    for (const [key, spanish] of Object.entries(esOnboarding)) {
      const english = (enOnboarding as Record<string, string | undefined>)[key];
      expect(english, key).toBeTruthy();
      expect(placeholders(english!), key).toEqual(placeholders(spanish));
    }
    expect(Object.keys(enOnboarding).sort()).toEqual(Object.keys(esOnboarding).sort());
  });

  it("does not override or get overridden by other dictionary parts", () => {
    for (const [key, spanish] of Object.entries(esOnboarding)) {
      expect(es[key as keyof typeof es], key).toBe(spanish);
    }
  });

  it("follows the Spanish writing rules", () => {
    for (const [key, spanish] of Object.entries(esOnboarding)) {
      expect(spanish, key).not.toMatch(/\.\.\./);
      expect(spanish.trim(), key).toBe(spanish);
      if (spanish.endsWith("?")) expect(spanish, key).toMatch(/¿/);
    }
  });
});
