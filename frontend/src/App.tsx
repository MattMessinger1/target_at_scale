import { Routes, Route } from 'react-router-dom'
import { Toaster } from '@/components/ui/toaster'
import Layout from '@/components/Layout'
import Dashboard from '@/pages/Dashboard'
import Districts from '@/pages/Districts'
import DistrictDetail from '@/pages/DistrictDetail'
import KnowledgeBase from '@/pages/KnowledgeBase'
import Export from '@/pages/Export'
import EmailGenerator from '@/pages/EmailGenerator'
import SavedRuns from '@/pages/SavedRuns'
import TrainingFeedback from '@/pages/TrainingFeedback'

function App() {
  return (
    <>
      <Routes>
        {/* Main V1 Email Generator - now the primary route */}
        <Route path="/" element={<EmailGenerator />} />
        <Route path="/generator" element={<EmailGenerator />} />
        <Route path="/saved-runs" element={<SavedRuns />} />
        <Route path="/training" element={<TrainingFeedback />} />
        
        {/* Legacy district-based routes under /admin */}
        <Route path="/admin" element={<Layout />}>
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
