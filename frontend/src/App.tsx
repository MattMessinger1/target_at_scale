import { Routes, Route } from 'react-router-dom'
import { Toaster } from '@/components/ui/toaster'
import Layout from '@/components/Layout'
import Dashboard from '@/pages/Dashboard'
import Districts from '@/pages/Districts'
import DistrictDetail from '@/pages/DistrictDetail'
import KnowledgeBase from '@/pages/KnowledgeBase'
import Export from '@/pages/Export'
import Landing from '@/pages/Landing'
import EmailGenerator from '@/pages/EmailGenerator'
import SavedRuns from '@/pages/SavedRuns'
import TrainingFeedback from '@/pages/TrainingFeedback'
import ResearchCoverage from '@/pages/ResearchCoverage'
import ResearchLibrary from '@/pages/ResearchLibrary'

function App() {
  return (
    <>
      <Routes>
        {/* Landing page - choose Research or Email flow */}
        <Route path="/" element={<Landing />} />
        
        {/* Research flow - focused on discovering opportunities */}
        <Route path="/research" element={<EmailGenerator mode="research" />} />
        
        {/* Email flow - focused on generating emails */}
        <Route path="/email" element={<EmailGenerator mode="email" />} />
        <Route path="/generator" element={<EmailGenerator mode="email" />} />
        
        {/* Other pages */}
        <Route path="/coverage" element={<ResearchCoverage />} />
        <Route path="/research-library" element={<ResearchLibrary />} />
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
