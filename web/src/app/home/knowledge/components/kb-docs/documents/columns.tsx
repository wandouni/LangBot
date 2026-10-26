import { ColumnDef } from '@tanstack/react-table';
import { MoreHorizontal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { TFunction } from 'i18next';

export type DocumentFile = {
  uuid: string;
  name: string;
  status: string;
};

export const columns = (
  onDelete: (id: string, name: string) => void,
  t: TFunction,
): ColumnDef<DocumentFile>[] => {
  return [
    {
      id: 'select',
      header: ({ table }) => (
        <Checkbox
          checked={
            table.getIsAllPageRowsSelected()
              ? true
              : table.getIsSomePageRowsSelected()
                ? 'indeterminate'
                : false
          }
          onCheckedChange={(value) =>
            table.toggleAllPageRowsSelected(value === true)
          }
          aria-label={t('knowledge.documentsTab.selectAll')}
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={row.getIsSelected()}
          onCheckedChange={(value) => row.toggleSelected(value === true)}
          aria-label={t('knowledge.documentsTab.selectRow')}
        />
      ),
      enableSorting: false,
      enableHiding: false,
      meta: {
        headerClassName: 'w-10',
        cellClassName: 'w-10',
      },
    },
    {
      accessorKey: 'name',
      header: t('knowledge.documentsTab.name'),
      meta: {
        headerClassName: 'w-full',
        cellClassName: 'w-full max-w-0',
      },
      cell: ({ row }) => {
        const name = row.original.name;

        return (
          <Tooltip>
            <TooltipTrigger asChild>
              <span
                tabIndex={0}
                dir="auto"
                className="block max-w-full truncate rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
              >
                {name}
              </span>
            </TooltipTrigger>
            <TooltipContent
              side="top"
              className="max-w-[min(24rem,calc(100vw-2rem))] whitespace-normal break-all text-left"
            >
              <span dir="auto">{name}</span>
            </TooltipContent>
          </Tooltip>
        );
      },
    },
    {
      accessorKey: 'status',
      header: t('knowledge.documentsTab.status'),
      cell: ({ row }) => {
        const document = row.original;

        switch (document.status) {
          case 'processing':
            return (
              <Badge variant="secondary">
                {t('knowledge.documentsTab.processing')}
              </Badge>
            );
          case 'completed':
            return (
              <Badge variant="outline" className="bg-blue-500 text-white">
                {t('knowledge.documentsTab.completed')}
              </Badge>
            );
          case 'failed':
            return (
              <Badge variant="outline" className="bg-yellow-500 text-white">
                {t('knowledge.documentsTab.failed')}
              </Badge>
            );
          default:
            return (
              <Badge variant="outline" className="bg-gray-500 text-white">
                {document.status}
              </Badge>
            );
        }
      },
    },
    {
      id: 'actions',
      cell: ({ row }) => {
        const document = row.original;

        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="h-8 w-8 p-0">
                <span className="sr-only">
                  {t('knowledge.documentsTab.actions')}
                </span>
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="bg-white dark:bg-[#2a2a2e]"
            >
              <DropdownMenuLabel>
                {t('knowledge.documentsTab.actions')}
              </DropdownMenuLabel>

              <DropdownMenuItem
                onClick={() => onDelete(document.uuid, document.name)}
              >
                {t('knowledge.documentsTab.delete')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ];
};
