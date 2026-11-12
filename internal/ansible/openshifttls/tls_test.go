// Copyright 2026 The Operator-SDK Authors
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

package openshifttls

import (
	"context"
	"crypto/tls"
	"errors"
	"testing"

	configv1 "github.com/openshift/api/config/v1"
	tlspkg "github.com/openshift/controller-runtime-common/pkg/tls"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	apimachruntime "k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/rest"
	ctrlclient "sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/manager"
)

func newFakeClientWithScheme(objs ...ctrlclient.Object) ctrlclient.Client {
	scheme := apimachruntime.NewScheme()
	if err := configv1.AddToScheme(scheme); err != nil {
		panic(err)
	}
	return fake.NewClientBuilder().WithScheme(scheme).WithObjects(objs...).Build()
}

func newFakeAPIServer(profileType configv1.TLSProfileType) *configv1.APIServer {
	return &configv1.APIServer{
		ObjectMeta: metav1.ObjectMeta{Name: tlspkg.APIServerName},
		Spec: configv1.APIServerSpec{
			TLSSecurityProfile: &configv1.TLSSecurityProfile{Type: profileType},
		},
	}
}

func TestClusterTLSPolicy_Apply(t *testing.T) {
	testCases := []struct {
		name                       string
		apiServer                  *configv1.APIServer
		wantMinVersion             uint16
		wantCipherSuites           bool
		wantProfileSourceAvailable bool
	}{
		{
			name:                       "Modern profile",
			apiServer:                  newFakeAPIServer(configv1.TLSProfileModernType),
			wantMinVersion:             tls.VersionTLS13,
			wantCipherSuites:           false,
			wantProfileSourceAvailable: true,
		},
		{
			name:                       "Intermediate profile",
			apiServer:                  newFakeAPIServer(configv1.TLSProfileIntermediateType),
			wantMinVersion:             tls.VersionTLS12,
			wantCipherSuites:           true,
			wantProfileSourceAvailable: true,
		},
		{
			name:                       "missing APIServer object falls back to default",
			apiServer:                  nil,
			wantMinVersion:             tls.VersionTLS12,
			wantCipherSuites:           true,
			wantProfileSourceAvailable: false,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			var objs []ctrlclient.Object
			if tc.apiServer != nil {
				objs = append(objs, tc.apiServer)
			}
			fakeC := newFakeClientWithScheme(objs...)

			p := &clusterTLSPolicy{
				fakeClient: func(_ *rest.Config, _ ctrlclient.Options) (ctrlclient.Client, error) {
					return fakeC, nil
				},
			}

			options, err := p.Apply(context.Background(), &rest.Config{}, manager.Options{})
			require.NoError(t, err)
			require.Len(t, options.Metrics.TLSOpts, 1)
			assert.Equal(t, tc.wantProfileSourceAvailable, p.profileSourceAvailable)

			cfg := &tls.Config{} //nolint:gosec // test-only, not used for a real connection
			options.Metrics.TLSOpts[0](cfg)
			assert.Equal(t, tc.wantMinVersion, cfg.MinVersion)
			if tc.wantCipherSuites {
				assert.NotEmpty(t, cfg.CipherSuites)
			} else {
				assert.Empty(t, cfg.CipherSuites)
			}
		})
	}
}

func TestClusterTLSPolicy_Apply_ClientConstructionFailureReturnsError(t *testing.T) {
	wantErr := errors.New("boom")
	p := &clusterTLSPolicy{
		fakeClient: func(_ *rest.Config, _ ctrlclient.Options) (ctrlclient.Client, error) {
			return nil, wantErr
		},
	}

	options, err := p.Apply(context.Background(), &rest.Config{}, manager.Options{})
	assert.ErrorIs(t, err, wantErr)
	assert.Empty(t, options.Metrics.TLSOpts)
}

func TestClusterTLSPolicy_Watch_SkipsWhenProfileSourceUnavailable(t *testing.T) {
	p := &clusterTLSPolicy{profileSourceAvailable: false}
	err := p.WatchIfProfileAvailable(context.Background(), nil, func() {})
	assert.NoError(t, err)
}
