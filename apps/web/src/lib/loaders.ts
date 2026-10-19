/**
 * Settled reads by name: a page starts every independent request at once, then renders each
 * card from its own result, so one failed call leaves a note on its card instead of failing
 * the page.
 */

type SettledRecord<T extends Record<string, Promise<unknown>>> = {
  [K in keyof T]: PromiseSettledResult<Awaited<T[K]>>;
};

export async function settledRecord<T extends Record<string, Promise<unknown>>>(
  tasks: T,
): Promise<SettledRecord<T>> {
  const keys = Object.keys(tasks) as (keyof T)[];
  const results = await Promise.allSettled(keys.map((key) => tasks[key]));
  return Object.fromEntries(keys.map((key, index) => [key, results[index]])) as SettledRecord<T>;
}

/** The value of a settled read, or null when it failed. */
export function settledValue<T>(result: PromiseSettledResult<T>): T | null {
  return result.status === "fulfilled" ? result.value : null;
}
