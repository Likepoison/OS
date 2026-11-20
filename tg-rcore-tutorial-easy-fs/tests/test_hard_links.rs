use std::sync::{Arc, Mutex};
use tg_rcore_tutorial_easy_fs::{BLOCK_SZ, BlockDevice, EasyFileSystem};

struct MemoryDisk(Mutex<Vec<[u8; BLOCK_SZ]>>);

impl BlockDevice for MemoryDisk {
    fn read_block(&self, block: usize, dst: &mut [u8]) {
        dst.copy_from_slice(&self.0.lock().unwrap()[block]);
    }

    fn write_block(&self, block: usize, src: &[u8]) {
        self.0.lock().unwrap()[block].copy_from_slice(src);
    }
}

#[test]
fn final_unlink_defers_reclamation_until_last_handle_closes() {
    let disk = Arc::new(MemoryDisk(Mutex::new(vec![[0; BLOCK_SZ]; 2048])));
    let fs = EasyFileSystem::create(disk.clone(), 2048, 1);
    let root = EasyFileSystem::root_inode(&fs);
    let original = root.create("original").unwrap();
    let (number, links) = original.file_stat().unwrap();
    assert_eq!(links, 1);
    let first_free_block = {
        let mut fs = fs.lock();
        let block = fs.alloc_data();
        fs.dealloc_data(block);
        block
    };
    assert_eq!(original.write_at(0, b"hello"), 5);
    assert!(root.link("original", "alias"));
    assert!(!root.link("original", "original"));
    assert!(!root.link("missing", "another"));

    let alias = root.find("alias").unwrap();
    assert!(Arc::ptr_eq(&original, &alias));
    assert_eq!(alias.file_stat(), Some((number, 2)));
    assert!(root.unlink("original"));
    assert!(root.find("original").is_none());
    assert_eq!(alias.file_stat(), Some((number, 1)));
    assert!(root.unlink("alias"));
    assert!(!root.unlink("alias"));
    assert!(root.readdir().is_empty());
    assert_eq!(original.file_stat(), Some((number, 0)));

    let mut data = [0; 5];
    assert_eq!(alias.read_at(0, &mut data), data.len());
    assert_eq!(&data, b"hello");
    assert_ne!(root.create("other").unwrap().file_stat().unwrap().0, number);
    drop(alias);
    drop(original);

    let recovered = root.create("recovered").unwrap();
    assert_eq!(recovered.file_stat(), Some((number, 1)));
    assert_eq!(recovered.read_at(0, &mut data), 0);
    {
        let mut fs = fs.lock();
        let block = fs.alloc_data();
        assert_eq!(block, first_free_block);
        fs.dealloc_data(block);
    }

    assert!(root.link("recovered", "kept"));
    drop(recovered);
    drop(root);
    drop(fs);
    let reopened = EasyFileSystem::open(disk);
    let root = EasyFileSystem::root_inode(&reopened);
    assert_eq!(root.find("kept").unwrap().file_stat(), Some((number, 2)));
}
