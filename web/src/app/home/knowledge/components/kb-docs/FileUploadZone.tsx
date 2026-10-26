import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { CloudUpload } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { httpClient } from '@/app/infra/http/HttpClient';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { ParserInfo } from '@/app/infra/entities/api';
import { CustomApiError, I18nObject } from '@/app/infra/entities/common';
import { extractI18nObject } from '@/i18n/I18nProvider';

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface FileUploadZoneProps {
  kbId: string;
  ragEngineName?: I18nObject;
  ragEngineCapabilities?: string[];
  onUploadSuccess: () => void;
  onUploadError: (error: string) => void;
}

export default function FileUploadZone({
  kbId,
  ragEngineName,
  ragEngineCapabilities,
  onUploadSuccess,
  onUploadError,
}: FileUploadZoneProps) {
  const { t } = useTranslation();
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  // Parser selection state
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [availableParsers, setAvailableParsers] = useState<ParserInfo[]>([]);
  const [selectedParser, setSelectedParser] = useState<string>('builtin');
  const [loadingParsers, setLoadingParsers] = useState(false);

  // Synchronous re-entrancy lock. `isUploading` only updates on the next
  // render, so two triggers in the same tick could both start uploading the
  // same files and create duplicate knowledge-base entries.
  const uploadInFlightRef = useRef(false);

  // Whether the Knowledge Engine natively supports document parsing.
  // This is a coarse-grained capability check rather than per-MIME-type filtering.
  // Fine-grained MIME type declaration (e.g. supported_parse_mime_types on the engine)
  // would require changes across the SDK, backend, and frontend prop chain;
  // using an engine-level capability flag keeps the change minimal.
  const ragEngineCanParse =
    ragEngineCapabilities?.includes('doc_parsing') ?? false;

  // Discover parsers shared by every selected file type. A batch is uploaded
  // with one parser, so only parsers that support all selected types are valid.
  useEffect(() => {
    if (pendingFiles.length === 0) return;

    let cancelled = false;
    setLoadingParsers(true);

    const loadParsers = async () => {
      const mimeTypes = Array.from(
        new Set(pendingFiles.map((file) => file.type || '')),
      );
      const parserLists = await Promise.all(
        mimeTypes.map(async (mimeType) => {
          try {
            const response = await httpClient.listParsers(
              mimeType || undefined,
            );
            return response.parsers || [];
          } catch {
            return [];
          }
        }),
      );

      if (cancelled) return;

      let commonParsers = parserLists[0] ?? [];
      for (const parsers of parserLists.slice(1)) {
        const pluginIds = new Set(parsers.map((parser) => parser.plugin_id));
        commonParsers = commonParsers.filter((parser) =>
          pluginIds.has(parser.plugin_id),
        );
      }

      setAvailableParsers(commonParsers);
      if (ragEngineCanParse) {
        setSelectedParser('builtin');
      } else {
        setSelectedParser(commonParsers[0]?.plugin_id ?? '');
      }
      setLoadingParsers(false);
    };

    void loadParsers();

    return () => {
      cancelled = true;
    };
  }, [pendingFiles, ragEngineCanParse]);

  const doUpload = useCallback(
    async (files: File[], parserPluginId?: string) => {
      if (uploadInFlightRef.current || files.length === 0) return;
      uploadInFlightRef.current = true;
      setIsUploading(true);

      try {
        const toastId = toast.loading(
          t('knowledge.documentsTab.uploadingFilesProgress', {
            current: 0,
            total: files.length,
          }),
        );

        let succeeded = 0;
        const failed: File[] = [];
        let firstError = '';

        // Upload sequentially so progress is predictable and the ingestion
        // service is not flooded by a large drop.
        for (let index = 0; index < files.length; index += 1) {
          const file = files[index];
          toast.loading(
            t('knowledge.documentsTab.uploadingFilesProgress', {
              current: index + 1,
              total: files.length,
            }),
            { id: toastId, description: file.name },
          );

          try {
            // Step 1: Upload file to server
            const uploadResult = await httpClient.uploadDocumentFile(file);

            // Step 2: Associate file with knowledge base (with optional parser)
            await httpClient.uploadKnowledgeBaseFile(
              kbId,
              uploadResult.file_id,
              parserPluginId,
              uploadResult.original_file_name || file.name,
            );
            succeeded += 1;
          } catch (error) {
            console.error('File upload failed:', file.name, error);
            failed.push(file);
            if (!firstError) {
              firstError = (error as CustomApiError).msg || '';
            }
          }
        }

        if (failed.length === 0) {
          toast.success(t('knowledge.documentsTab.uploadSuccess'), {
            id: toastId,
          });
        } else {
          const failedNames = failed.map((file) => file.name).join(', ');
          if (succeeded === 0) {
            toast.error(t('knowledge.documentsTab.uploadError') + firstError, {
              id: toastId,
              description: failedNames,
            });
          } else {
            toast.error(
              t('knowledge.documentsTab.uploadPartialFailure', {
                files: failed.length,
              }),
              { id: toastId, description: failedNames },
            );
          }
          onUploadError(failedNames);
        }

        if (succeeded > 0) {
          onUploadSuccess();
        }
      } finally {
        uploadInFlightRef.current = false;
        setIsUploading(false);
        setPendingFiles([]);
        setAvailableParsers([]);
        setSelectedParser('builtin');
      }
    },
    [kbId, onUploadSuccess, onUploadError, t],
  );

  const handleFilesSelected = useCallback(
    (files: File[]) => {
      if (isUploading || uploadInFlightRef.current || files.length === 0) {
        return;
      }

      const accepted = files.filter((file) => file.size <= MAX_FILE_SIZE);
      const rejected = files.filter((file) => file.size > MAX_FILE_SIZE);

      if (rejected.length > 0) {
        toast.error(t('knowledge.documentsTab.fileSizeExceeded'), {
          description: rejected.map((file) => file.name).join(', '),
        });
      }
      if (accepted.length === 0) return;

      // Set loadingParsers=true BEFORE pendingFiles so both state updates
      // batch together in the same render. This prevents the auto-upload
      // effect from firing before parser fetch completes.
      setLoadingParsers(true);
      setPendingFiles(accepted);
    },
    [isUploading, t],
  );

  // Auto-upload if Knowledge Engine can parse and no external parsers available
  useEffect(() => {
    if (
      pendingFiles.length > 0 &&
      !isUploading &&
      !uploadInFlightRef.current &&
      !loadingParsers &&
      ragEngineCanParse &&
      availableParsers.length === 0
    ) {
      void doUpload(pendingFiles);
    }
  }, [
    pendingFiles,
    isUploading,
    loadingParsers,
    ragEngineCanParse,
    availableParsers,
    doUpload,
  ]);

  const handleConfirmUpload = useCallback(() => {
    if (pendingFiles.length === 0) return;
    const parserPluginId =
      selectedParser === 'builtin' ? undefined : selectedParser;
    void doUpload(pendingFiles, parserPluginId);
  }, [pendingFiles, selectedParser, doUpload]);

  const handleCancelUpload = useCallback(() => {
    setPendingFiles([]);
    setAvailableParsers([]);
    setSelectedParser('builtin');
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);

      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) {
        handleFilesSelected(files);
      }
    },
    [handleFilesSelected],
  );

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files ?? []);
      if (files.length > 0) {
        handleFilesSelected(files);
      }
      // Reset the input so the same file can be selected again
      e.target.value = '';
    },
    [handleFilesSelected],
  );

  // Show parser selection UI when there are choices to make, or when no parser is available
  const showParserSelector =
    pendingFiles.length > 0 &&
    !loadingParsers &&
    (availableParsers.length > 0 || !ragEngineCanParse);

  const noParserAvailable = !ragEngineCanParse && availableParsers.length === 0;
  const noCommonParser = pendingFiles.length > 1;

  return (
    <Card className="mb-4">
      <CardContent className="p-4">
        {showParserSelector ? (
          <div className="space-y-3">
            <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
              {t('knowledge.documentsTab.filesSelected', {
                files: pendingFiles.length,
              })}
            </p>
            <div className="max-h-40 space-y-1 overflow-y-auto rounded-md border p-2">
              {pendingFiles.map((file, index) => (
                <div
                  key={`${file.name}-${file.size}-${index}`}
                  className="flex items-center justify-between gap-3 text-sm"
                >
                  <span className="truncate" dir="auto" title={file.name}>
                    {file.name}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {formatFileSize(file.size)}
                  </span>
                </div>
              ))}
            </div>
            {noParserAvailable ? (
              <div className="rounded-md bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 p-3">
                <p className="text-sm text-yellow-800 dark:text-yellow-200">
                  {noCommonParser
                    ? t('knowledge.documentsTab.noCommonParser')
                    : t('knowledge.documentsTab.noParserAvailable')}
                </p>
                <Link
                  to="/home/add-extension"
                  className="text-sm text-primary hover:underline mt-1 inline-block"
                >
                  {t('knowledge.documentsTab.installParserHint')}
                </Link>
              </div>
            ) : (
              <div className="space-y-2">
                <label className="text-sm text-gray-600 dark:text-gray-400">
                  {t('knowledge.documentsTab.selectParser')}
                </label>
                <Select
                  value={selectedParser}
                  onValueChange={setSelectedParser}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ragEngineCanParse && (
                      <SelectItem value="builtin">
                        {ragEngineName
                          ? extractI18nObject(ragEngineName)
                          : t('knowledge.documentsTab.builtInParser')}
                      </SelectItem>
                    )}
                    {availableParsers.map((parser) => (
                      <SelectItem
                        key={parser.plugin_id}
                        value={parser.plugin_id}
                      >
                        {extractI18nObject(parser.name)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={handleCancelUpload}>
                {t('knowledge.documentsTab.cancelUpload')}
              </Button>
              {!noParserAvailable && (
                <Button size="sm" onClick={handleConfirmUpload}>
                  {t('knowledge.documentsTab.confirmUpload')}
                </Button>
              )}
            </div>
          </div>
        ) : (
          <div
            className={`
              relative border-2 border-dashed rounded-lg p-4 text-center transition-colors
              ${
                isDragOver
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-300 hover:border-gray-400'
              }
              ${isUploading || loadingParsers ? 'opacity-50 pointer-events-none' : ''}
            `}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <input
              type="file"
              id="file-upload"
              className="hidden"
              onChange={handleFileSelect}
              accept=".pdf,.doc,.docx,.txt,.md,.html,.zip"
              multiple
              disabled={isUploading || loadingParsers}
            />

            <label htmlFor="file-upload" className="cursor-pointer block">
              <div className="space-y-2">
                <div className="mx-auto w-10 h-10 bg-gray-100 rounded-full flex items-center justify-center">
                  <CloudUpload className="w-5 h-5 text-gray-400" />
                </div>

                <div>
                  <p className="text-base font-medium text-gray-900 dark:text-gray-100">
                    {isUploading
                      ? t('knowledge.documentsTab.uploading')
                      : t('knowledge.documentsTab.dragAndDrop')}
                  </p>
                  <p className="text-xs text-gray-500 mt-1 dark:text-gray-400">
                    {t('knowledge.documentsTab.supportedFormats')}
                  </p>
                </div>
              </div>
            </label>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
