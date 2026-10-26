import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { RowSelectionState } from '@tanstack/react-table';
import { Trash2 } from 'lucide-react';
import { httpClient } from '@/app/infra/http/HttpClient';
import { KnowledgeBaseFile } from '@/app/infra/entities/api';
import { I18nObject, CustomApiError } from '@/app/infra/entities/common';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { columns, DocumentFile } from './documents/columns';
import { DataTable } from './documents/data-table';
import { resolveDocumentName } from './documents/documentName';
import FileUploadZone from './FileUploadZone';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';

type DeleteRequest = {
  ids: string[];
  name?: string;
};

export default function KBDoc({
  kbId,
  ragEngineName,
  ragEngineCapabilities,
}: {
  kbId: string;
  ragEngineName?: I18nObject;
  ragEngineCapabilities?: string[];
}) {
  const [documentsList, setDocumentsList] = useState<DocumentFile[]>([]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [deleteRequest, setDeleteRequest] = useState<DeleteRequest | null>(
    null,
  );
  const [deleting, setDeleting] = useState(false);
  const { t } = useTranslation();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const getDocumentsList = useCallback(async () => {
    const resp = await httpClient.getKnowledgeBaseFiles(kbId);
    const files = resp.files.map((file: KnowledgeBaseFile) => ({
      uuid: file.uuid,
      name: resolveDocumentName(file),
      status: file.status,
    }));
    setDocumentsList(files);
    return files;
  }, [kbId]);

  const startPolling = useCallback(() => {
    if (intervalRef.current) return;
    intervalRef.current = setInterval(() => {
      getDocumentsList().then((files) => {
        const allDone =
          files.length > 0 &&
          files.every(
            (doc: DocumentFile) =>
              doc.status === 'completed' || doc.status === 'failed',
          );
        if (allDone && intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      });
    }, 5000);
  }, [getDocumentsList]);

  useEffect(() => {
    getDocumentsList().then((files) => {
      const hasProcessing = files.some(
        (doc: DocumentFile) =>
          doc.status !== 'completed' && doc.status !== 'failed',
      );
      if (hasProcessing) {
        startPolling();
      }
    });

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [kbId, getDocumentsList, startPolling]);

  // Keep these callbacks stable: FileUploadZone derives its upload callback
  // from them, and a new identity on every poll-driven render would re-arm
  // its auto-upload effect.
  const handleUploadSuccess = useCallback(() => {
    getDocumentsList();
    startPolling();
  }, [getDocumentsList, startPolling]);

  const handleUploadError = useCallback((error: string) => {
    console.error('Upload failed:', error);
  }, []);

  const selectedIds = useMemo(
    () =>
      documentsList
        .filter((document) => rowSelection[document.uuid])
        .map((document) => document.uuid),
    [documentsList, rowSelection],
  );

  const requestDelete = useCallback((ids: string[], name?: string) => {
    if (ids.length === 0) return;
    setDeleteRequest({ ids, name });
  }, []);

  const handleConfirmDelete = async () => {
    if (!deleteRequest || deleting) return;

    const ids = deleteRequest.ids;
    setDeleting(true);

    const failedIds: string[] = [];
    let firstError = '';

    // Delete sequentially: the service updates the knowledge base and its
    // upstream index per file, and partial failures should not abort the rest.
    for (const id of ids) {
      try {
        await httpClient.deleteKnowledgeBaseFile(kbId, id);
      } catch (error) {
        console.error('Delete failed:', id, error);
        failedIds.push(id);
        if (!firstError) {
          firstError = (error as CustomApiError).msg || '';
        }
      }
    }

    setDeleting(false);
    setDeleteRequest(null);
    setRowSelection(
      Object.fromEntries(
        failedIds.map((id) => [id, true]),
      ) as RowSelectionState,
    );

    await getDocumentsList().catch((error) => {
      console.error('Refresh failed:', error);
    });

    if (failedIds.length === 0) {
      toast.success(t('knowledge.documentsTab.fileDeleteSuccess'));
    } else if (failedIds.length === ids.length) {
      toast.error(t('knowledge.documentsTab.fileDeleteFailed') + firstError);
    } else {
      toast.error(
        t('knowledge.documentsTab.deletePartialFailure', {
          files: failedIds.length,
        }),
      );
    }
  };

  return (
    <div className="container mx-auto py-2">
      <FileUploadZone
        kbId={kbId}
        ragEngineName={ragEngineName}
        ragEngineCapabilities={ragEngineCapabilities}
        onUploadSuccess={handleUploadSuccess}
        onUploadError={handleUploadError}
      />
      {selectedIds.length > 0 && (
        <div className="mb-2 flex items-center justify-between gap-2 rounded-md border bg-muted/40 px-3 py-2">
          <span className="text-sm text-muted-foreground">
            {t('knowledge.documentsTab.selectedCount', {
              files: selectedIds.length,
            })}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setRowSelection({})}
            >
              {t('knowledge.documentsTab.clearSelection')}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => requestDelete(selectedIds)}
            >
              <Trash2 className="mr-1 h-4 w-4" />
              {t('knowledge.documentsTab.deleteSelected')}
            </Button>
          </div>
        </div>
      )}
      <DataTable
        columns={columns(
          (id: string, name: string) => requestDelete([id], name),
          t,
        )}
        data={documentsList}
        getRowId={(document) => document.uuid}
        rowSelection={rowSelection}
        onRowSelectionChange={setRowSelection}
      />

      <AlertDialog
        open={deleteRequest !== null}
        onOpenChange={(open) => {
          if (!open && !deleting) {
            setDeleteRequest(null);
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('common.confirmDelete')}</AlertDialogTitle>
            <AlertDialogDescription>
              {deleteRequest?.ids.length === 1 && deleteRequest.name
                ? t('knowledge.documentsTab.deleteSingleConfirm', {
                    name: deleteRequest.name,
                  })
                : t('knowledge.documentsTab.deleteBatchConfirm', {
                    files: deleteRequest?.ids.length ?? 0,
                  })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>
              {t('common.cancel')}
            </AlertDialogCancel>
            <Button
              variant="destructive"
              disabled={deleting}
              onClick={() => {
                void handleConfirmDelete();
              }}
            >
              {deleting
                ? t('knowledge.documentsTab.deleting')
                : t('common.confirmDelete')}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
