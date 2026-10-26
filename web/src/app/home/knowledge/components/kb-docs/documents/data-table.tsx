import { useState } from 'react';
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  OnChangeFn,
  RowSelectionState,
  useReactTable,
} from '@tanstack/react-table';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';

interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[];
  data: TData[];
  getRowId?: (row: TData) => string;
  rowSelection?: RowSelectionState;
  onRowSelectionChange?: OnChangeFn<RowSelectionState>;
}

export function DataTable<TData, TValue>({
  columns,
  data,
  getRowId,
  rowSelection,
  onRowSelectionChange,
}: DataTableProps<TData, TValue>) {
  const { t } = useTranslation();
  const [internalRowSelection, setInternalRowSelection] =
    useState<RowSelectionState>({});
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId,
    enableRowSelection: true,
    state: {
      rowSelection: rowSelection ?? internalRowSelection,
    },
    onRowSelectionChange: onRowSelectionChange ?? setInternalRowSelection,
  });

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => {
                return (
                  <TableHead
                    key={header.id}
                    className={cn(
                      (
                        header.column.columnDef.meta as
                          { headerClassName?: string } | undefined
                      )?.headerClassName,
                    )}
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows?.length ? (
            table.getRowModel().rows.map((row) => (
              <TableRow
                key={row.id}
                data-state={row.getIsSelected() && 'selected'}
                className={row.getIsSelected() ? 'bg-muted/50' : undefined}
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell
                    key={cell.id}
                    className={cn(
                      (
                        cell.column.columnDef.meta as
                          { cellClassName?: string } | undefined
                      )?.cellClassName,
                    )}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableRow>
              <TableCell colSpan={columns.length} className="h-24 text-center">
                {t('knowledge.documentsTab.noResults')}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
