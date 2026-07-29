import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  BoxSelect,
  Check,
  ChevronLeft,
  FileText,
  Frame,
  Image as ImageIcon,
  LoaderCircle,
  Maximize2,
  Plus,
  Redo2,
  Save,
  Search,
  Sparkles,
  StickyNote,
  Trash2,
  Undo2,
  WandSparkles,
  X
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import {
  CANVAS_NODE_TYPES,
  MATERIAL_LABELS,
  RESOURCE_LABELS,
  createCanvasId,
  createResourceNode,
  nodeIcon,
  persistCanvasEdge,
  persistCanvasNode
} from './CanvasNodes'
import './Canvas.css'

const EMPTY_VIEWPORT = { x: 0, y: 0, zoom: 1 }

function CanvasInner ({ notify, onNavigate }) {
  const flow = useReactFlow()
  const canvasRef = useRef(null)
  const viewportRef = useRef(EMPTY_VIEWPORT)
  const readyRef = useRef(false)
  const saveTimerRef = useRef(null)
  const lastSavedRef = useRef('')
  const historyRef = useRef({ past: [], future: [] })

  const [boards, setBoards] = useState([])
  const [active, setActive] = useState(null)
  const [title, setTitle] = useState('')
  const [nodes, setNodes] = useState([])
  const [edges, setEdges] = useState([])
  const [viewportTick, setViewportTick] = useState(0)
  const [saveState, setSaveState] = useState('saved')
  const [libraryOpen, setLibraryOpen] = useState(
    () => window.innerWidth > 760
  )
  const [inspectorOpen, setInspectorOpen] = useState(
    () => window.innerWidth > 760
  )
  const [libraryTab, setLibraryTab] = useState('all')
  const [libraryQuery, setLibraryQuery] = useState('')
  const [library, setLibrary] = useState([])
  const [loadingLibrary, setLoadingLibrary] = useState(true)
  const [aiDialog, setAiDialog] = useState(false)
  const [aiForm, setAiForm] = useState({
    topic: '',
    article_type: 'article',
    requirements: '',
    word_count: 1200,
    image_count: 5
  })

  const selectedNodes = nodes.filter(node => node.selected)
  const selectedNode = selectedNodes.length === 1 ? selectedNodes[0] : null

  const canvasDocument = useMemo(() => ({
    nodes: nodes.map(persistCanvasNode),
    edges: edges.map(persistCanvasEdge),
    viewport: viewportRef.current
  }), [nodes, edges, viewportTick])

  const signature = useMemo(
    () => JSON.stringify({ title, document: canvasDocument }),
    [title, canvasDocument]
  )

  const openBoard = async canvasId => {
    readyRef.current = false
    const item = await api.canvas(canvasId)
    setActive(item)
    setTitle(item.title)
    setNodes(item.document.nodes || [])
    setEdges(item.document.edges || [])
    viewportRef.current = item.document.viewport || EMPTY_VIEWPORT
    historyRef.current = { past: [], future: [] }
    window.requestAnimationFrame(() => {
      if (window.innerWidth <= 760 && item.document.nodes?.length) {
        flow.fitView({ padding: 0.16, duration: 0 })
      } else {
        flow.setViewport(viewportRef.current, { duration: 0 })
      }
      lastSavedRef.current = JSON.stringify({
        title: item.title,
        document: item.document
      })
      setSaveState('saved')
      readyRef.current = true
    })
  }

  const loadBoards = async preferredId => {
    const items = await api.canvases()
    setBoards(items)
    const nextId = preferredId || items[0]?.id
    if (nextId) await openBoard(nextId)
    else {
      readyRef.current = false
      setActive(null)
      setTitle('')
      setNodes([])
      setEdges([])
    }
  }

  useEffect(() => {
    Promise.all([
      api.canvases(),
      api.articles(),
      api.news(),
      api.materials()
    ]).then(([canvasItems, articles, news, materials]) => {
      setBoards(canvasItems)
      setLibrary([
        ...articles.map(item => ({
          ...item,
          resourceType: 'article',
          statusLabel: item.article_type === 'image'
            ? '图文'
            : item.article_type === 'video' ? '视频' : '文章'
        })),
        ...news.items.map(item => ({ ...item, resourceType: 'news' })),
        ...materials.items.map(item => ({ ...item, resourceType: 'material' }))
      ])
      if (canvasItems[0]) return openBoard(canvasItems[0].id)
      return null
    }).catch(error => notify(error.message, 'error'))
      .finally(() => setLoadingLibrary(false))
  }, [])

  useEffect(() => {
    if (!active || !readyRef.current || signature === lastSavedRef.current) return
    setSaveState('pending')
    window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = window.setTimeout(async () => {
      setSaveState('saving')
      try {
        const saved = await api.updateCanvas(active.id, {
          title,
          document: canvasDocument
        })
        setActive(saved)
        lastSavedRef.current = JSON.stringify({
          title: saved.title,
          document: saved.document
        })
        setSaveState('saved')
        setBoards(current => current.map(item => (
          item.id === saved.id
            ? {
                ...item,
                title: saved.title,
                version: saved.version,
                updated_at: saved.updated_at,
                node_count: saved.document.nodes.length,
                edge_count: saved.document.edges.length
              }
            : item
        )))
      } catch (error) {
        setSaveState('error')
        notify('画布保存失败：' + error.message, 'error')
      }
    }, 900)
    return () => window.clearTimeout(saveTimerRef.current)
  }, [active?.id, signature])

  const snapshot = () => ({
    nodes: nodes.map(node => ({ ...node, data: { ...node.data } })),
    edges: edges.map(edge => ({ ...edge }))
  })

  const remember = () => {
    const history = historyRef.current
    history.past.push(snapshot())
    if (history.past.length > 50) history.past.shift()
    history.future = []
  }

  const restore = state => {
    setNodes(state.nodes)
    setEdges(state.edges)
  }

  const undo = () => {
    const state = historyRef.current.past.pop()
    if (!state) return
    historyRef.current.future.push(snapshot())
    restore(state)
  }

  const redo = () => {
    const state = historyRef.current.future.pop()
    if (!state) return
    historyRef.current.past.push(snapshot())
    restore(state)
  }

  const onNodesChange = changes => {
    if (changes.some(change => change.type === 'remove')) remember()
    setNodes(current => applyNodeChanges(changes, current))
  }

  const onEdgesChange = changes => {
    if (changes.some(change => change.type === 'remove')) remember()
    setEdges(current => applyEdgeChanges(changes, current))
  }

  const onConnect = connection => {
    remember()
    setEdges(current => addEdge({
      ...connection,
      id: createCanvasId('edge'),
      type: 'smoothstep',
      markerEnd: { type: MarkerType.ArrowClosed }
    }, current))
  }

  const centerPosition = (width = 270, height = 150) => {
    const bounds = canvasRef.current?.getBoundingClientRect()
    const center = flow.screenToFlowPosition({
      x: bounds ? bounds.left + bounds.width / 2 : window.innerWidth / 2,
      y: bounds ? bounds.top + bounds.height / 2 : window.innerHeight / 2
    })
    const offset = (nodes.length % 6) * 22
    return {
      x: center.x - width / 2 + offset,
      y: center.y - height / 2 + offset
    }
  }

  const addNode = node => {
    remember()
    if (window.innerWidth <= 760) {
      setLibraryOpen(false)
      setInspectorOpen(true)
    }
    setNodes(current => [
      ...current.map(item => ({ ...item, selected: false })),
      { ...node, selected: true }
    ])
  }

  const addNote = () => addNode({
    id: createCanvasId('note'),
    type: 'note',
    position: centerPosition(230, 160),
    data: { title: '新想法', content: '' }
  })

  const addGroup = () => addNode({
    id: createCanvasId('group'),
    type: 'group',
    position: centerPosition(520, 320),
    width: 520,
    height: 320,
    zIndex: -1,
    data: { title: '内容分组', color: '#c65a3a' }
  })

  const removeSelected = () => {
    const ids = new Set(selectedNodes.map(node => node.id))
    if (!ids.size && !edges.some(edge => edge.selected)) return
    remember()
    setNodes(current => current.filter(node => !ids.has(node.id)))
    setEdges(current => current.filter(edge => (
      !edge.selected && !ids.has(edge.source) && !ids.has(edge.target)
    )))
  }

  useEffect(() => {
    const onKeyDown = event => {
      const editing = ['INPUT', 'TEXTAREA', 'SELECT']
        .includes(window.document.activeElement?.tagName)
      if (editing) return
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        if (event.shiftKey) redo()
        else undo()
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') {
        event.preventDefault()
        redo()
      } else if (event.key === 'Delete' || event.key === 'Backspace') {
        removeSelected()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [nodes, edges])

  const filteredLibrary = library.filter(item => {
    if (libraryTab !== 'all' && item.resourceType !== libraryTab) return false
    const term = libraryQuery.trim().toLowerCase()
    if (!term) return true
    return [item.title, item.summary, item.description, item.content_md]
      .some(value => String(value || '').toLowerCase().includes(term))
  })

  const addResource = (item, position = centerPosition(270, 150)) => {
    addNode(createResourceNode(item, position))
  }

  const onDrop = event => {
    event.preventDefault()
    try {
      const item = JSON.parse(
        event.dataTransfer.getData('application/moflow-resource')
      )
      addResource(
        item,
        flow.screenToFlowPosition({ x: event.clientX, y: event.clientY })
      )
    } catch {
      // Ignore unrelated drops.
    }
  }

  const updateSelectedData = values => {
    if (!selectedNode) return
    setNodes(current => current.map(node => (
      node.id === selectedNode.id
        ? { ...node, data: { ...node.data, ...values } }
        : node
    )))
  }

  const createBoard = async () => {
    try {
      const created = await api.createCanvas({ title: '未命名画布' })
      await loadBoards(created.id)
      notify('画布已创建')
    } catch (error) {
      notify(error.message, 'error')
    }
  }

  const deleteBoard = async () => {
    if (
      !active ||
      !window.confirm('确定删除画布“' + title + '”吗？内容库资源不会被删除。')
    ) return
    try {
      await api.deleteCanvas(active.id)
      await loadBoards()
      notify('画布已删除')
    } catch (error) {
      notify(error.message, 'error')
    }
  }

  const saveNoteAsMaterial = async () => {
    if (!selectedNode || selectedNode.type !== 'note') return
    const content = selectedNode.data.content?.trim()
    if (!content) {
      notify('卡片笔记内容不能为空', 'error')
      return
    }
    try {
      const material = await api.createMaterialNote({
        title: selectedNode.data.title || '未命名卡片',
        content_md: content,
        description: '',
        tags: []
      })
      setLibrary(current => [
        { ...material, resourceType: 'material' },
        ...current
      ])
      setNodes(current => current.map(node => (
        node.id === selectedNode.id
          ? {
              ...createResourceNode(
                { ...material, resourceType: 'material' },
                node.position
              ),
              id: node.id,
              selected: true
            }
          : node
      )))
      notify('已保存到素材库')
    } catch (error) {
      notify(error.message, 'error')
    }
  }
  const runAiGeneration = async event => {
    event.preventDefault()
    const references = selectedNodes
      .filter(node => node.type === 'resource')
      .map(node => node.data)
    const taskId = createCanvasId('ai')
    addNode({
      id: taskId,
      type: 'ai',
      position: centerPosition(270, 140),
      data: {
        status: 'running',
        title: aiForm.article_type === 'image' ? '生成图文' : '生成文章',
        message: '正在整理 ' + references.length + ' 条参考内容'
      }
    })
    setAiDialog(false)
    notify('AI 任务已放到画布后台运行')

    const materialIds = references
      .filter(item => item.resourceType === 'material')
      .map(item => item.resourceId)
    const newsIds = references
      .filter(item => item.resourceType === 'news')
      .map(item => item.resourceId)
    const articleTitles = references
      .filter(item => item.resourceType === 'article')
      .map(item => item.title)
    const requirements = [
      aiForm.requirements,
      articleTitles.length
        ? '可参考这些已有稿件的选题方向：' + articleTitles.join('、')
        : ''
    ].filter(Boolean).join('\n')
    const payload = {
      topic: aiForm.topic,
      article_type: aiForm.article_type,
      author: '',
      audience: '',
      style: '',
      requirements,
      word_count: Number(aiForm.word_count),
      image_count: aiForm.article_type === 'image'
        ? Number(aiForm.image_count)
        : 1,
      image_mode: 'auto',
      material_ids: materialIds,
      news_ids: newsIds
    }

    try {
      if (payload.article_type === 'image') {
        const storyboard = await api.generateStoryboard(payload)
        payload.storyboard = storyboard
        payload.image_count = storyboard.pages.length
      }
      const article = await api.generateArticle(payload)
      setLibrary(current => [
        { ...article, resourceType: 'article' },
        ...current
      ])
      setNodes(current => current.map(node => (
        node.id === taskId
          ? {
              ...createResourceNode({
                ...article,
                resourceType: 'article',
                statusLabel: article.article_type === 'image'
                  ? '图文'
                  : '文章'
              }, node.position),
              id: taskId,
              selected: true
            }
          : { ...node, selected: false }
      )))
      notify('稿件已生成并保存到内容库')
    } catch (error) {
      setNodes(current => current.map(node => (
        node.id === taskId
          ? {
              ...node,
              data: {
                ...node.data,
                status: 'failed',
                message: '生成失败',
                error: error.message
              }
            }
          : node
      )))
      notify('AI 生成失败：' + error.message, 'error')
    }
  }

  if (!active) {
    return (
      <section className='canvas-empty-page'>
        <div>
          <Frame size={34} />
          <h2>还没有内容画布</h2>
          <button className='button vermilion' onClick={createBoard}>
            <Plus size={16} />
            新建画布
          </button>
        </div>
      </section>
    )
  }

  return (
    <section className='canvas-page'>
      <div className='canvas-commandbar'>
        <div className='canvas-board-switcher'>
          <select
            value={active.id}
            onChange={event => openBoard(Number(event.target.value))}
          >
            {boards.map(board => (
              <option value={board.id} key={board.id}>
                {board.title}
              </option>
            ))}
          </select>
          <button title='新建画布' onClick={createBoard}>
            <Plus size={16} />
          </button>
          <button title='删除画布' onClick={deleteBoard}>
            <Trash2 size={15} />
          </button>
        </div>
        <input
          className='canvas-title-input'
          value={title}
          onChange={event => setTitle(event.target.value)}
          maxLength={120}
          aria-label='画布名称'
        />
        <div className={'canvas-save-state ' + saveState}>
          {saveState === 'saving' && (
            <LoaderCircle className='spin' size={14} />
          )}
          {saveState === 'saved' && <Check size={14} />}
          {saveState === 'pending' && <Save size={14} />}
          {saveState === 'error' && <X size={14} />}
          {saveState === 'saving'
            ? '保存中'
            : saveState === 'pending'
              ? '待保存'
              : saveState === 'error' ? '保存失败' : '已保存'}
        </div>
      </div>

      <div className='canvas-stage-shell'>
        <aside className={'canvas-library ' + (libraryOpen ? 'open' : 'closed')}>
          <header>
            <div>
              <BoxSelect size={16} />
              <b>资源库</b>
            </div>
            <button
              title='收起资源库'
              onClick={() => setLibraryOpen(false)}
            >
              <ChevronLeft size={16} />
            </button>
          </header>
          <div className='canvas-library-search'>
            <Search size={14} />
            <input
              value={libraryQuery}
              onChange={event => setLibraryQuery(event.target.value)}
              placeholder='搜索内容'
            />
          </div>
          <div className='canvas-library-tabs'>
            {[
              ['all', '全部'],
              ['article', '稿件'],
              ['news', '资讯'],
              ['material', '素材']
            ].map(([key, label]) => (
              <button
                className={libraryTab === key ? 'active' : ''}
                onClick={() => setLibraryTab(key)}
                key={key}
              >
                {label}
              </button>
            ))}
          </div>
          <div className='canvas-library-list'>
            {loadingLibrary && (
              <div className='canvas-library-empty'>
                <LoaderCircle className='spin' size={18} />
              </div>
            )}
            {!loadingLibrary && filteredLibrary.slice(0, 100).map(item => (
              <div
                className='canvas-library-item'
                key={item.resourceType + '-' + item.id}
                draggable
                onDragStart={event => {
                  event.dataTransfer.effectAllowed = 'copy'
                  event.dataTransfer.setData(
                    'application/moflow-resource',
                    JSON.stringify(item)
                  )
                }}
                onDoubleClick={() => addResource(item)}
              >
                <span>{nodeIcon(item)}</span>
                <div>
                  <b>{item.title}</b>
                  <small>
                    {item.resourceType === 'material'
                      ? MATERIAL_LABELS[item.kind]
                      : RESOURCE_LABELS[item.resourceType]}
                  </small>
                </div>
                <button
                  title='添加到画布'
                  onClick={event => {
                    event.stopPropagation()
                    addResource(item)
                  }}
                >
                  <Plus size={14} />
                </button>
              </div>
            ))}
            {!loadingLibrary && !filteredLibrary.length && (
              <div className='canvas-library-empty'>没有匹配内容</div>
            )}
          </div>
        </aside>

        {!libraryOpen && (
          <button
            className='canvas-drawer-toggle left'
            title='打开资源库'
            onClick={() => {
              setLibraryOpen(true)
              if (window.innerWidth <= 760) setInspectorOpen(false)
            }}
          >
            <BoxSelect size={17} />
          </button>
        )}

        <div
          className='canvas-flow'
          ref={canvasRef}
          onDrop={onDrop}
          onDragOver={event => {
            event.preventDefault()
            event.dataTransfer.dropEffect = 'copy'
          }}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={CANVAS_NODE_TYPES}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeDragStart={remember}
            onMoveEnd={(_, viewport) => {
              viewportRef.current = viewport
              setViewportTick(value => value + 1)
            }}
            fitView={!nodes.length}
            minZoom={0.15}
            maxZoom={2.5}
            snapToGrid
            snapGrid={[16, 16]}
            deleteKeyCode={null}
            selectionOnDrag
            panOnScroll
            selectionMode='partial'
            defaultEdgeOptions={{
              type: 'smoothstep',
              markerEnd: { type: MarkerType.ArrowClosed }
            }}
          >
            <Background gap={24} size={1} color='#d8d2c8' />
            <MiniMap
              pannable
              zoomable
              nodeColor={node => (
                node.type === 'note'
                  ? '#e9b949'
                  : node.type === 'group'
                    ? '#c9beb1'
                    : node.data?.resourceType === 'news'
                      ? '#367d78'
                      : '#c65a3a'
              )}
            />
            <Controls showInteractive={false} />
            <div className='canvas-floating-toolbar'>
              <button title='添加便签' onClick={addNote}>
                <StickyNote size={17} />
              </button>
              <button title='添加分组' onClick={addGroup}>
                <Frame size={17} />
              </button>
              <span />
              <button
                title='撤销'
                disabled={!historyRef.current.past.length}
                onClick={undo}
              >
                <Undo2 size={17} />
              </button>
              <button
                title='重做'
                disabled={!historyRef.current.future.length}
                onClick={redo}
              >
                <Redo2 size={17} />
              </button>
              <button
                title='适应画布'
                onClick={() => flow.fitView({ padding: 0.2, duration: 260 })}
              >
                <Maximize2 size={17} />
              </button>
              <span />
              <button
                className='ai-action'
                title='AI 生成'
                aria-label='AI 生成'
                onClick={() => setAiDialog(true)}
              >
                <WandSparkles size={17} />
                <b aria-hidden='true'>{selectedNodes.length || ''}</b>
              </button>
              <button
                title='删除选中'
                disabled={!selectedNodes.length}
                onClick={removeSelected}
              >
                <Trash2 size={17} />
              </button>
            </div>
          </ReactFlow>
        </div>
        {!inspectorOpen && (
          <button
            className='canvas-drawer-toggle right'
            title='打开属性面板'
            onClick={() => {
              setInspectorOpen(true)
              if (window.innerWidth <= 760) setLibraryOpen(false)
            }}
          >
            <FileText size={17} />
          </button>
        )}

        <aside className={'canvas-inspector ' + (inspectorOpen ? 'open' : 'closed')}>
          <header>
            <div>
              <FileText size={16} />
              <b>属性</b>
            </div>
            <button
              title='收起属性面板'
              onClick={() => setInspectorOpen(false)}
            >
              <X size={16} />
            </button>
          </header>
          {!selectedNode && (
            <div className='canvas-inspector-empty'>
              <BoxSelect size={24} />
              <b>
                {selectedNodes.length > 1
                  ? '已选择 ' + selectedNodes.length + ' 个节点'
                  : '未选择节点'}
              </b>
            </div>
          )}
          {selectedNode?.type === 'note' && (
            <div className='canvas-inspector-form'>
              <label>
                <span>标题</span>
                <input
                  value={selectedNode.data.title || ''}
                  onChange={event => updateSelectedData({
                    title: event.target.value
                  })}
                />
              </label>
              <label>
                <span>内容</span>
                <textarea
                  value={selectedNode.data.content || ''}
                  onChange={event => updateSelectedData({
                    content: event.target.value
                  })}
                />
              </label>
              <button className='button ink' onClick={saveNoteAsMaterial}>
                <Save size={15} />
                保存为卡片笔记
              </button>
            </div>
          )}
          {selectedNode?.type === 'group' && (
            <div className='canvas-inspector-form'>
              <label>
                <span>分组名称</span>
                <input
                  value={selectedNode.data.title || ''}
                  onChange={event => updateSelectedData({
                    title: event.target.value
                  })}
                />
              </label>
              <label>
                <span>标记颜色</span>
                <input
                  type='color'
                  value={selectedNode.data.color || '#c65a3a'}
                  onChange={event => updateSelectedData({
                    color: event.target.value
                  })}
                />
              </label>
            </div>
          )}
          {selectedNode?.type === 'resource' && (
            <div className='canvas-resource-detail'>
              <span className={'node-kind ' + selectedNode.data.resourceType}>
                {nodeIcon(selectedNode.data)}
                {selectedNode.data.resourceType === 'material'
                  ? MATERIAL_LABELS[selectedNode.data.kind]
                  : RESOURCE_LABELS[selectedNode.data.resourceType]}
              </span>
              <h3>{selectedNode.data.title}</h3>
              {selectedNode.data.summary && <p>{selectedNode.data.summary}</p>}
              <button
                className='button ink'
                onClick={() => onNavigate(
                  selectedNode.data.resourceType === 'article'
                    ? 'articles'
                    : selectedNode.data.resourceType === 'news'
                      ? 'news'
                      : 'materials'
                )}
              >
                打开来源
              </button>
            </div>
          )}
          {selectedNode?.type === 'ai' && (
            <div className='canvas-resource-detail'>
              <span className='node-kind ai'>
                <Sparkles size={15} />
                AI 任务
              </span>
              <h3>{selectedNode.data.title}</h3>
              <p>{selectedNode.data.message}</p>
              {selectedNode.data.error && (
                <div className='canvas-ai-error'>
                  {selectedNode.data.error}
                </div>
              )}
            </div>
          )}
        </aside>
      </div>

      {aiDialog && (
        <div
          className='modal-backdrop'
          onMouseDown={() => setAiDialog(false)}
        >
          <form
            className='canvas-ai-dialog'
            onSubmit={runAiGeneration}
            onMouseDown={event => event.stopPropagation()}
          >
            <header>
              <div>
                <span className='eyebrow'>CANVAS TO CONTENT</span>
                <h2>从画布生成</h2>
              </div>
              <button
                type='button'
                className='close-button'
                onClick={() => setAiDialog(false)}
              >
                <X size={18} />
              </button>
            </header>
            <div className='canvas-ai-reference-count'>
              <BoxSelect size={17} />
              已选择 {selectedNodes.length} 个节点
            </div>
            <label className='field full'>
              <span>主题</span>
              <input
                autoFocus
                required
                minLength={2}
                value={aiForm.topic}
                onChange={event => setAiForm(current => ({
                  ...current,
                  topic: event.target.value
                }))}
              />
            </label>
            <div className='canvas-ai-type'>
              <button
                type='button'
                className={aiForm.article_type === 'article' ? 'active' : ''}
                onClick={() => setAiForm(current => ({
                  ...current,
                  article_type: 'article'
                }))}
              >
                <FileText size={16} />
                文章
              </button>
              <button
                type='button'
                className={aiForm.article_type === 'image' ? 'active' : ''}
                onClick={() => setAiForm(current => ({
                  ...current,
                  article_type: 'image'
                }))}
              >
                <ImageIcon size={16} />
                图文
              </button>
            </div>
            <label className='field full'>
              <span>补充要求</span>
              <textarea
                value={aiForm.requirements}
                onChange={event => setAiForm(current => ({
                  ...current,
                  requirements: event.target.value
                }))}
              />
            </label>
            <div className='canvas-ai-numbers'>
              <label className='field'>
                <span>字数</span>
                <input
                  type='number'
                  min='300'
                  max='5000'
                  value={aiForm.word_count}
                  onChange={event => setAiForm(current => ({
                    ...current,
                    word_count: event.target.value
                  }))}
                />
              </label>
              {aiForm.article_type === 'image' && (
                <label className='field'>
                  <span>页数</span>
                  <input
                    type='number'
                    min='1'
                    max='9'
                    value={aiForm.image_count}
                    onChange={event => setAiForm(current => ({
                      ...current,
                      image_count: event.target.value
                    }))}
                  />
                </label>
              )}
            </div>
            <footer>
              <button
                type='button'
                className='button paper'
                onClick={() => setAiDialog(false)}
              >
                取消
              </button>
              <button className='button vermilion'>
                <WandSparkles size={16} />
                开始生成
              </button>
            </footer>
          </form>
        </div>
      )}
    </section>
  )
}

export default function Canvas (props) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  )
}
