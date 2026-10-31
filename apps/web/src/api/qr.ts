/** QR modules as rows of "0"/"1" (see `QrMatrix` in the backend). */
export type QrMatrix = {
  rows: string[];
  size: number;
};

export type ApiErrorBody = {
  code: string;
  details?: Record<string, unknown>;
  message: string;
};
