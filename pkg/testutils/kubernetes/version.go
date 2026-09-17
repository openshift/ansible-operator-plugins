package kubernetes

import (
	"encoding/json"
	"strings"
)

// VersionInfo represents the version information that is returned when running something like `kubectl version`
type VersionInfo interface {
	// Major returns the string representation of the Major version
	Major() string
	// Minor returns the string representatiion of the Minor version
	Minor() string
	// GitVersion returns the string representation of the GitVersion
	GitVersion() string
}

// KubernetesVersion represents the JSON response that is returned when running something like `kubectl version`
type KubernetesVersion interface {
	// ClientVersion returns the VersionInfo for the client
	ClientVersion() VersionInfo
	// ServerVersion returns the VersionInfo for the server
	ServerVersion() VersionInfo
}

// kubeVersionInfoJSON is a struct that allows for easier parsing of the JSON version information from something like `kubectl version`
type kubeVersionInfoJSON struct {
	Major      string `json:"major"`
	Minor      string `json:"minor"`
	GitVersion string `json:"gitVersion"`
}

// KubeVersionInfo is an implementation of the VersionInfo interface
type KubeVersionInfo struct {
	kubeVersionInfoJSON
}

// NewKubeVersionInfo will return a KubeVersionInfo from a given JSON string
func NewKubeVersionInfo(out string) (*KubeVersionInfo, error) {
	kvi := &KubeVersionInfo{}
	dec := json.NewDecoder(strings.NewReader(out))
	if err := dec.Decode(&kvi.kubeVersionInfoJSON); err != nil {
		return nil, err
	}

	return kvi, nil
}

// Major returns the string representation of the Major version
func (kvi *KubeVersionInfo) Major() string {
	return kvi.kubeVersionInfoJSON.Major
}

// Minor returns the string representatiion of the Minor version
func (kvi *KubeVersionInfo) Minor() string {
	return kvi.kubeVersionInfoJSON.Minor
}

// GitVersion returns the string representation of the GitVersion
func (kvi *KubeVersionInfo) GitVersion() string {
	return kvi.kubeVersionInfoJSON.GitVersion
}

// KubeVersion is an implementation of the KubernetesVersion interface
type KubeVersion struct {
	clientVersion KubeVersionInfo
	serverVersion KubeVersionInfo
}

// KubeVersionOptions is for configuring a KubeVersion
type KubeVersionOptions func(kv *KubeVersion)

// WithClientVersion will set the ClientVersion for a KubeVersion
func WithClientVersion(clientVersion VersionInfo) KubeVersionOptions {
	return func(kv *KubeVersion) {
		kv.clientVersion = KubeVersionInfo{
			kubeVersionInfoJSON: kubeVersionInfoJSON{
				Major:      clientVersion.Major(),
				Minor:      clientVersion.Minor(),
				GitVersion: clientVersion.GitVersion(),
			},
		}
	}
}

// WithServerVersion configures the ServerVersion for a KubeVersion
func WithServerVersion(serverVersion VersionInfo) KubeVersionOptions {
	return func(kv *KubeVersion) {
		kv.serverVersion = KubeVersionInfo{
			kubeVersionInfoJSON: kubeVersionInfoJSON{
				Major:      serverVersion.Major(),
				Minor:      serverVersion.Minor(),
				GitVersion: serverVersion.GitVersion(),
			},
		}
	}
}

// NewKubeVersion returns a new KubeVersion and can be configured via KubeVersionOptions functions
func NewKubeVersion(opts ...KubeVersionOptions) *KubeVersion {
	kv := &KubeVersion{}

	for _, opt := range opts {
		opt(kv)
	}

	return kv
}

// ClientVersion returns the VersionInfo for the client
func (kv *KubeVersion) ClientVersion() VersionInfo {
	return &kv.clientVersion
}

// ServerVersion returns the VersionInfo for the server
func (kv *KubeVersion) ServerVersion() VersionInfo {
	return &kv.serverVersion
}
