/**
 * Expected failures (bad hex, a malformed header) come back as values so the
 * caller has to branch; exceptions are for bugs.
 */

type Result<T, E> =
  { readonly ok: true; readonly value: T } | { readonly ok: false; readonly error: E };

function ok<T>(value: T): Result<T, never> {
  return { ok: true, value };
}

function err<E>(error: E): Result<never, E> {
  return { ok: false, error };
}

export { ok, err, type Result };
