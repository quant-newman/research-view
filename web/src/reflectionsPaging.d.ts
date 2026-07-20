export const PER_PAGE: number;
export function totalPages(total: number, perPage?: number): number;
export function clampPage(page: number, total: number, perPage?: number): number;
export function pageSlice(page: number, total: number, perPage?: number):
  { page: number; start: number; end: number };
