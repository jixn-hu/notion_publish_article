import {
  Handle,
  NodeResizer,
  Position
} from '@xyflow/react'
import {
  FileText,
  Film,
  Frame,
  Image as ImageIcon,
  LoaderCircle,
  Newspaper,
  Sparkles,
  StickyNote
} from 'lucide-react'
import { materialFileUrl } from './api'

export const RESOURCE_LABELS = {
  article: '稿件',
  news: '资讯',
  material: '素材'
}

export const MATERIAL_LABELS = {
  image: '图片',
  video: '视频',
  note: '卡片笔记'
}

export function nodeIcon (data, size = 15) {
  if (data.resourceType === 'article') return <FileText size={size} />
  if (data.resourceType === 'news') return <Newspaper size={size} />
  if (data.kind === 'image') return <ImageIcon size={size} />
  if (data.kind === 'video') return <Film size={size} />
  return <StickyNote size={size} />
}

function NodeHandles () {
  return (
    <>
      <Handle type='target' position={Position.Left} />
      <Handle type='source' position={Position.Right} />
    </>
  )
}

function ResourceNode ({ data, selected }) {
  const isImage = data.resourceType === 'material' && data.kind === 'image'
  return (
    <article className={'canvas-node resource-node ' + (selected ? 'selected' : '')}>
      <NodeHandles />
      {isImage && (
        <img
          className='canvas-node-media'
          src={materialFileUrl(data.resourceId)}
          alt=''
          draggable='false'
        />
      )}
      <header>
        <span className={'node-kind ' + data.resourceType}>
          {nodeIcon(data)}
          {data.resourceType === 'material'
            ? MATERIAL_LABELS[data.kind] || '素材'
            : RESOURCE_LABELS[data.resourceType]}
        </span>
        {data.status && (
          <i className={'node-status ' + data.status}>
            {data.statusLabel || data.status}
          </i>
        )}
      </header>
      <h3>{data.title || '未命名内容'}</h3>
      {data.summary && <p>{data.summary}</p>}
      {!!data.tags?.length && (
        <footer>
          {data.tags.slice(0, 3).map(tag => <span key={tag}>{tag}</span>)}
        </footer>
      )}
    </article>
  )
}

function NoteNode ({ data, selected }) {
  return (
    <article className={'canvas-node note-node ' + (selected ? 'selected' : '')}>
      <NodeHandles />
      <header>
        <span className='node-kind note'>
          <StickyNote size={15} />
          便签
        </span>
      </header>
      <h3>{data.title || '新想法'}</h3>
      <p className='note-content'>{data.content || ''}</p>
    </article>
  )
}

function GroupNode ({ data, selected }) {
  return (
    <section
      className={'canvas-group-node ' + (selected ? 'selected' : '')}
      style={{ '--group-color': data.color || '#c65a3a' }}
    >
      <NodeResizer
        minWidth={280}
        minHeight={180}
        isVisible={selected}
        lineClassName='group-resize-line'
        handleClassName='group-resize-handle'
      />
      <header>
        <Frame size={14} />
        {data.title || '内容分组'}
      </header>
    </section>
  )
}

function AiNode ({ data, selected }) {
  const running = data.status === 'running'
  return (
    <article
      className={
        'canvas-node ai-node ' +
        (selected ? 'selected ' : '') +
        (data.status || '')
      }
    >
      <NodeHandles />
      <header>
        <span className='node-kind ai'>
          <Sparkles size={15} />
          AI 任务
        </span>
        {running && <LoaderCircle className='spin' size={15} />}
      </header>
      <h3>{data.title || '正在生成'}</h3>
      <p>{data.message || '正在整理参考内容'}</p>
      {data.error && <small>{data.error}</small>}
    </article>
  )
}

export const CANVAS_NODE_TYPES = {
  resource: ResourceNode,
  note: NoteNode,
  group: GroupNode,
  ai: AiNode
}

export const createCanvasId = prefix => prefix + '-' + crypto.randomUUID()

export function createResourceNode (item, position) {
  return {
    id: createCanvasId('resource'),
    type: 'resource',
    position,
    data: {
      resourceType: item.resourceType,
      resourceId: item.id,
      kind: item.kind || '',
      title: item.title,
      summary: item.summary || item.description || '',
      tags: item.tags || [],
      status: item.status || '',
      statusLabel: item.statusLabel || ''
    }
  }
}

export function persistCanvasNode (node) {
  const result = {
    id: node.id,
    type: node.type,
    position: node.position,
    data: node.data
  }
  if (node.width) result.width = node.width
  if (node.height) result.height = node.height
  if (node.parentId) {
    result.parentId = node.parentId
    result.extent = 'parent'
  }
  if (node.zIndex != null) result.zIndex = node.zIndex
  return result
}

export function persistCanvasEdge (edge) {
  const result = {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: edge.type || 'smoothstep'
  }
  if (edge.sourceHandle) result.sourceHandle = edge.sourceHandle
  if (edge.targetHandle) result.targetHandle = edge.targetHandle
  if (edge.label) result.label = edge.label
  if (edge.data) result.data = edge.data
  return result
}
