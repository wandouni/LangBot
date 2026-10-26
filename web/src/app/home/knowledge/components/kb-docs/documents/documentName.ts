export function storageKeyBasename(key?: string | null): string {
  const normalized = (key ?? '').replace(/\\/g, '/').replace(/\/+$/, '');
  if (!normalized) {
    return '';
  }
  const index = normalized.lastIndexOf('/');
  return index === -1 ? normalized : normalized.slice(index + 1);
}

export function resolveDocumentName(file: {
  file_name?: string | null;
  original_file_name?: string | null;
}): string {
  const original = file.original_file_name?.trim();
  if (original) {
    return original;
  }
  return storageKeyBasename(file.file_name) || '-';
}
