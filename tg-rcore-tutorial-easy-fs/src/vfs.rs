use super::{
    block_cache_sync_all, get_block_cache, BlockDevice, DirEntry, DiskInode, DiskInodeType,
    EasyFileSystem, DIRENT_SZ, NAME_LENGTH_LIMIT,
};
use alloc::string::String;
use alloc::sync::Arc;
use alloc::vec::Vec;
use core::sync::atomic::{AtomicBool, Ordering};
use spin::{Mutex, MutexGuard};
/// Virtual filesystem layer over easy-fs
pub struct Inode {
    block_id: usize,
    block_offset: usize,
    fs: Arc<Mutex<EasyFileSystem>>,
    block_device: Arc<dyn BlockDevice>,
    number: u32,
    unlinked: AtomicBool,
}

impl Inode {
    /// Create a vfs inode
    pub fn new(
        block_id: u32,
        block_offset: usize,
        fs: Arc<Mutex<EasyFileSystem>>,
        block_device: Arc<dyn BlockDevice>,
    ) -> Self {
        Self {
            block_id: block_id as usize,
            block_offset,
            fs,
            block_device,
            number: 0,
            unlinked: AtomicBool::new(false),
        }
    }

    fn open_inode(&self, fs: &mut EasyFileSystem, number: u32) -> Arc<Self> {
        if let Some(inode) = fs.handles.get(&number).and_then(alloc::sync::Weak::upgrade) {
            return inode;
        }
        let (block_id, block_offset) = fs.get_disk_inode_pos(number);
        let mut inode = Self::new(block_id, block_offset, self.fs.clone(), self.block_device.clone());
        inode.number = number;
        let inode = Arc::new(inode);
        fs.handles.insert(number, Arc::downgrade(&inode));
        inode
    }

    /// Call a function over a disk inode to read it
    fn read_disk_inode<V>(&self, f: impl FnOnce(&DiskInode) -> V) -> V {
        get_block_cache(self.block_id, Arc::clone(&self.block_device))
            .lock()
            .read(self.block_offset, f)
    }

    /// Call a function over a disk inode to modify it
    fn modify_disk_inode<V>(&self, f: impl FnOnce(&mut DiskInode) -> V) -> V {
        get_block_cache(self.block_id, Arc::clone(&self.block_device))
            .lock()
            .modify(self.block_offset, f)
    }

    fn dir_entries<'a>(&'a self, disk: &'a DiskInode) -> impl Iterator<Item = (usize, DirEntry)> + 'a {
        assert!(disk.is_dir());
        (0..disk.size as usize).step_by(DIRENT_SZ).map(move |offset| {
            let mut entry = DirEntry::empty();
            assert_eq!(disk.read_at(offset, entry.as_bytes_mut(), &self.block_device), DIRENT_SZ);
            (offset, entry)
        })
    }

    fn valid_name(name: &str) -> bool {
        !name.is_empty() && name.len() <= NAME_LENGTH_LIMIT && !name.as_bytes().contains(&0)
    }

    /// Find inode under current inode by name.
    pub fn find(&self, name: &str) -> Option<Arc<Inode>> {
        if !Self::valid_name(name) {
            return None;
        }
        let mut fs = self.fs.lock();
        let number = self.read_disk_inode(|disk| {
            self.dir_entries(disk)
                .find(|(_, entry)| entry.name() == name)
                .map(|(_, entry)| entry.inode_number())
        })?;
        Some(self.open_inode(&mut fs, number))
    }

    /// Increase the size of a disk inode
    fn increase_size(
        &self,
        new_size: u32,
        disk_inode: &mut DiskInode,
        fs: &mut MutexGuard<EasyFileSystem>,
    ) {
        if new_size < disk_inode.size {
            return;
        }
        // 先按“新增块数”批量申请数据块，再一次性扩容 inode。
        let blocks_needed = disk_inode.blocks_num_needed(new_size);
        let mut v: Vec<u32> = Vec::new();
        for _ in 0..blocks_needed {
            v.push(fs.alloc_data());
        }
        disk_inode.increase_size(new_size, v, &self.block_device);
    }

    fn add_entry(&self, disk: &mut DiskInode, fs: &mut MutexGuard<EasyFileSystem>, entry: DirEntry) {
        let offset = self.dir_entries(disk)
            .find(|(_, slot)| slot.inode_number() == 0)
            .map_or(disk.size as usize, |(offset, _)| offset);
        self.increase_size((offset + DIRENT_SZ) as u32, disk, fs);
        assert_eq!(disk.write_at(offset, entry.as_bytes(), &self.block_device), DIRENT_SZ);
    }

    /// Create a new file in this directory.
    pub fn create(&self, name: &str) -> Option<Arc<Inode>> {
        if !Self::valid_name(name) {
            return None;
        }
        let mut fs = self.fs.lock();
        if self.read_disk_inode(|disk| self.dir_entries(disk).any(|(_, item)| item.name() == name)) {
            return None;
        }
        let number = fs.alloc_inode();
        let (block_id, offset) = fs.get_disk_inode_pos(number);
        get_block_cache(block_id as usize, Arc::clone(&self.block_device))
            .lock()
            .modify(offset, |inode: &mut DiskInode| inode.initialize(DiskInodeType::File));
        self.modify_disk_inode(|disk| self.add_entry(disk, &mut fs, DirEntry::new(name, number)));
        block_cache_sync_all();
        Some(self.open_inode(&mut fs, number))
    }

    /// Create another name for a file in this directory.
    pub fn link(&self, source: &str, target: &str) -> bool {
        if !Self::valid_name(source) || !Self::valid_name(target) {
            return false;
        }
        let mut fs = self.fs.lock();
        let linked = self.modify_disk_inode(|disk| {
            let mut number = None;
            for (_, entry) in self.dir_entries(disk) {
                if entry.name() == target {
                    return false;
                }
                if entry.name() == source {
                    number = Some(entry.inode_number());
                }
            }
            let Some(number) = number else { return false };
            self.add_entry(disk, &mut fs, DirEntry::new(target, number));
            true
        });
        if linked {
            block_cache_sync_all();
        }
        linked
    }

    /// Remove a file name. Last-link reclamation waits for live handles to close.
    pub fn unlink(&self, name: &str) -> bool {
        if !Self::valid_name(name) {
            return false;
        }
        let mut fs = self.fs.lock();
        let result = self.modify_disk_inode(|disk| {
            let (offset, number) = self.dir_entries(disk)
                .find(|(_, entry)| entry.name() == name)
                .map(|(offset, entry)| (offset, entry.inode_number()))?;
            let last = !self.dir_entries(disk)
                .any(|(other, entry)| other != offset && entry.inode_number() == number);
            assert_eq!(
                disk.write_at(offset, DirEntry::empty().as_bytes(), &self.block_device),
                DIRENT_SZ,
            );
            Some((number, last))
        });
        let Some((number, last)) = result else { return false };
        let released = last.then(|| {
            let inode = self.open_inode(&mut fs, number);
            inode.unlinked.store(true, Ordering::Release);
            inode
        });
        block_cache_sync_all();
        drop(fs);
        drop(released);
        true
    }

    /// Return the inode number and live directory link count for an open file.
    pub fn file_stat(&self) -> Option<(u32, u32)> {
        if self.number == 0 {
            return None;
        }
        let fs = self.fs.lock();
        let (block, offset) = fs.get_disk_inode_pos(0);
        let root = Self::new(block, offset, self.fs.clone(), self.block_device.clone());
        let count = root.read_disk_inode(|disk| {
            root.dir_entries(disk).filter(|(_, entry)| entry.inode_number() == self.number).count()
        });
        Some((self.number, count as u32))
    }

    /// List names of live entries in this directory.
    pub fn readdir(&self) -> Vec<String> {
        let _fs = self.fs.lock();
        self.read_disk_inode(|disk| {
            self.dir_entries(disk)
                .filter(|(_, entry)| entry.inode_number() != 0)
                .map(|(_, entry)| String::from(entry.name()))
                .collect()
        })
    }

    /// Read data from current inode
    pub fn read_at(&self, offset: usize, buf: &mut [u8]) -> usize {
        let _fs = self.fs.lock();
        self.read_disk_inode(|disk_inode| disk_inode.read_at(offset, buf, &self.block_device))
    }

    /// Write data to current inode
    pub fn write_at(&self, offset: usize, buf: &[u8]) -> usize {
        let mut fs = self.fs.lock();
        let size = self.modify_disk_inode(|disk_inode| {
            self.increase_size((offset + buf.len()) as u32, disk_inode, &mut fs);
            disk_inode.write_at(offset, buf, &self.block_device)
        });
        block_cache_sync_all();
        size
    }

    /// Clear the data in current inode
    pub fn clear(&self) {
        let mut fs = self.fs.lock();
        self.clear_data(&mut fs);
        block_cache_sync_all();
    }

    fn clear_data(&self, fs: &mut EasyFileSystem) {
        self.modify_disk_inode(|disk_inode| {
            let size = disk_inode.size;
            let data_blocks_dealloc = disk_inode.clear_size(&self.block_device);
            assert!(data_blocks_dealloc.len() == DiskInode::total_blocks(size) as usize);
            for data_block in data_blocks_dealloc.into_iter() {
                fs.dealloc_data(data_block);
            }
        });
    }
}

impl Drop for Inode {
    fn drop(&mut self) {
        if !self.unlinked.load(Ordering::Acquire) {
            return;
        }
        let mut fs = self.fs.lock();
        self.clear_data(&mut fs);
        fs.inode_bitmap.dealloc(&fs.block_device, self.number as usize);
        fs.handles.remove(&self.number);
        block_cache_sync_all();
    }
}
