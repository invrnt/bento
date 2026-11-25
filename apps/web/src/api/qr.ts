/** QR modules as rows of "0"/"1" (see `QrMatrix` in the backend). */
export type QrMatrix = {
  /** Side, in modules, of the centred square cleared for the Bento mark; 0 or absent = no logo. */
  logo_modules?: number;
  rows: string[];
  size: number;
};

export type ApiErrorBody = {
  code: string;
  details?: Record<string, unknown>;
  message: string;
};
