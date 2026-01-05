import { Routes, Route } from 'react-router-dom'
import { Toaster } from '@/components/ui/toaster'
import Layout from '@/components/Layout'
import Dashboard from '@/pages/Dashboard'
import Districts from '@/pages/Districts'
import DistrictDetail from '@/pages/DistrictDetail'
import KnowledgeBase from '@/pages/KnowledgeBase'
import Export from '@/pages/Export'

function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="districts" element={<Districts />} />
          <Route path="districts/:districtId" element={<DistrictDetail />} />
          <Route path="knowledge-base" element={<KnowledgeBase />} />
          <Route path="export" element={<Export />} />
        </Route>
      </Routes>
      <Toaster />
    </>
  )
}

export default App
