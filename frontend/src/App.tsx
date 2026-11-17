import { useEffect, useState } from 'react'
import { Editor } from './editor/Editor'
import { ImportPage } from './ImportPage'
import { Permissions } from './Permissions'
import { SongList } from './SongList'

const route = () => window.location.hash

export function App() {
  const [hash, setHash] = useState(route)
  useEffect(() => {
    const on = () => setHash(route())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const song = hash.match(/^#\/song\/([a-z0-9-]+)(\/review)?$/) // old /review links just open the song
  if (song) return <Editor key={song[1]} id={song[1]} />
  if (hash === '#/import') return <ImportPage />
  return hash === '#/permissions' ? <Permissions /> : <SongList />
}
