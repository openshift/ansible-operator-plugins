// Copyright 2018 The Operator-SDK Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package eventapi

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/fsnotify/fsnotify"
	"github.com/go-logr/logr"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
)

// FileEventReceiver watches ansible-runner artifact files for events
type FileEventReceiver struct {
	// Events is the channel used to send JobEvents back to the runner
	Events chan JobEvent

	// ArtifactPath is the path where ansible-runner writes artifact files
	ArtifactPath string

	// stopped indicates if this receiver has permanently stopped receiving events
	stopped bool

	// mutex controls access to the "stopped" bool
	mutex sync.RWMutex

	// ident is the unique identifier for a particular run of ansible-runner
	ident string

	// logger holds a logger that has some fields already set
	logger logr.Logger

	// errChan is a channel for errors
	errChan chan<- error

	// ctx is the context for cancellation
	ctx        context.Context
	cancelFunc context.CancelFunc

	// processedFiles keeps track of which files have been processed
	processedFiles map[string]bool
	processMutex   sync.Mutex

	// wg tracks goroutines for clean shutdown
	wg sync.WaitGroup
}

// NewFileEventReceiver creates a new file-based event receiver
func NewFileEventReceiver(ident string, artifactPath string, errChan chan<- error) (*FileEventReceiver, error) {
	ctx, cancel := context.WithCancel(context.Background())

	receiver := &FileEventReceiver{
		Events:         make(chan JobEvent, 1000),
		ArtifactPath:   artifactPath,
		ident:          ident,
		logger:         logf.Log.WithName("fileapi").WithValues("job", ident),
		errChan:        errChan,
		ctx:            ctx,
		cancelFunc:     cancel,
		processedFiles: make(map[string]bool),
	}

	// Start watching for file changes
	receiver.wg.Add(1)
	go receiver.watchJobEvents()

	return receiver, nil
}

// watchJobEvents monitors the job_events directory for new files
func (f *FileEventReceiver) watchJobEvents() {
	defer f.wg.Done()
	defer close(f.Events)

	// Watch the job_events directory
	// Ansible-runner writes artifacts to {inputDir}/artifacts/{ident}/job_events
	jobEventsDir := filepath.Join(f.ArtifactPath, "artifacts", f.ident, "job_events")

	// Ensure directory exists before watching
	if err := os.MkdirAll(jobEventsDir, 0755); err != nil {
		f.errChan <- fmt.Errorf("failed to create job_events directory: %v", err)
		return
	}

	f.logger.Info("Starting file-based event receiver", "jobEventsDir", jobEventsDir)

	// Watch for new files
	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		f.errChan <- fmt.Errorf("failed to create file watcher: %v", err)
		return
	}
	defer watcher.Close()

	if err := watcher.Add(jobEventsDir); err != nil {
		f.errChan <- fmt.Errorf("failed to watch job_events directory: %v", err)
		return
	}

	for {
		select {
		case event, ok := <-watcher.Events:
			if !ok {
				return
			}
			// Process CREATE and WRITE events for JSON files
			if (event.Op&fsnotify.Create == fsnotify.Create ||
				event.Op&fsnotify.Write == fsnotify.Write) &&
				filepath.Ext(event.Name) == ".json" {
				time.Sleep(100 * time.Millisecond) // Brief delay to ensure file is fully written
				f.processEventFile(event.Name)
			}
		case err, ok := <-watcher.Errors:
			if !ok {
				return
			}
			f.errChan <- fmt.Errorf("file watcher error: %v", err)
		case <-f.ctx.Done():
			f.logger.V(1).Info("Context cancelled")
			return
		}
	}
}

// processEventFile reads and parses a single event file
func (r *FileEventReceiver) processEventFile(filename string) bool {
	// Check if already processed
	r.processMutex.Lock()
	if r.processedFiles[filename] {
		r.processMutex.Unlock()
		r.logger.Info("Already processed file", "file", filename)
		return true
	}
	r.processMutex.Unlock()

	// Add small delay to ensure file is fully written
	time.Sleep(50 * time.Millisecond)

	file, err := os.Open(filename)
	if err != nil {
		r.logger.V(2).Info("Could not open event file (may not be ready)", "file", filename)
		return false
	}
	defer file.Close()

	// Parse JSON event from file
	var event JobEvent
	decoder := json.NewDecoder(file)
	if err := decoder.Decode(&event); err != nil {
		// Skip files that aren't valid JSON (might be partial writes)
		r.logger.V(2).Info("Could not parse event file (may be incomplete)", "file", filename, "error", err)
		return false
	}

	// Mark as processed
	r.processMutex.Lock()
	r.processedFiles[filename] = true
	r.processMutex.Unlock()

	// Check if receiver is stopped
	r.mutex.RLock()
	stopped := r.stopped
	r.mutex.RUnlock()

	if stopped {
		r.logger.V(1).Info("Receiver stopped, dropping event", "event", event.Event)
		return false
	}

	// Send event to channel with timeout
	timeout := time.NewTimer(10 * time.Second)
	defer timeout.Stop()

	select {
	case r.Events <- event:
		r.logger.V(2).Info("Processed event", "event", event.Event, "uuid", event.UUID)
		if event.Event == EventPlaybookOnStats {
			r.logger.Info("Successfully processed playbook_on_stats event")
		}
		return true
	case <-timeout.C:
		r.logger.Info("Timed out writing event to channel")
		return true
	case <-r.ctx.Done():
		r.logger.V(1).Info("Context cancelled while writing event")
		return false
	}
}

// Close ensures that appropriate resources are cleaned up
func (r *FileEventReceiver) Close() {
	r.mutex.Lock()
	r.stopped = true
	r.mutex.Unlock()

	// Cancel context to signal goroutines to stop
	if r.cancelFunc != nil {
		r.cancelFunc()
	}

	// Wait for all goroutines to finish
	r.wg.Wait()

	r.logger.V(1).Info("File Event API stopped")
}
