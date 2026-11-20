import React, { useState, useEffect, useRef } from 'react';
import {
  StyleSheet,
  Text,
  View,
  TextInput,
  TouchableOpacity,
  ScrollView,
  SafeAreaView,
  StatusBar,
  Vibration,
  Alert,
  Switch,
  Platform,
} from 'react-native';

export default function App() {
  const [serverUrl, setServerUrl] = useState('https://cheddar-banjo-agile.ngrok-free.dev');
  const [darkMode, setDarkMode] = useState(false);
  const [awayMode, setAwayMode] = useState(true);

  // Auth State
  const [user, setUser] = useState(null);
  const [authMode, setAuthMode] = useState('login');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [authError, setAuthError] = useState('');

  // Navigation & Live Stream State
  const [activeTab, setActiveTab] = useState('dashboard');
  const [connected, setConnected] = useState(false);
  const [simPhrase, setSimPhrase] = useState('Areesha attendance lag rahi hai');
  const [transcripts, setTranscripts] = useState([]);
  const [alerts, setAlerts] = useState([]);

  // Session Notes & Auto-Title State
  const [liveNotes, setLiveNotes] = useState([]);
  const [generatedTitle, setGeneratedTitle] = useState('');
  const [savedBanner, setSavedBanner] = useState(false);

  // Triggers & Saved Notes State
  const [triggers, setTriggers] = useState([]);
  const [newTrigger, setNewTrigger] = useState('');
  const [savedNotes, setSavedNotes] = useState([]);

  const wsRef = useRef(null);
  const awayModeRef = useRef(awayMode);
  awayModeRef.current = awayMode;

  // Editorial Palette matching EchoNote Desktop
  const theme = darkMode
    ? {
        headerBg: '#0D1512',
        bg: '#111614',
        card: '#19201D',
        subtle: '#222C28',
        border: '#2A3531',
        text: '#F3F4F2',
        muted: '#8F9995',
        accent: '#2E7D6B',
        pillBg: '#1D332D',
        pillText: '#7CC4B2',
        amberBg: '#3A2E1A',
        amberText: '#E5B567',
      }
    : {
        headerBg: '#14211D',
        bg: '#F6F4EF',
        card: '#FFFFFF',
        subtle: '#EDF2F0',
        border: '#E5E2DC',
        text: '#18201D',
        muted: '#6E7774',
        accent: '#1D4E43',
        pillBg: '#E6F0EC',
        pillText: '#1D4E43',
        amberBg: '#F7EEDB',
        amberText: '#9A6715',
      };

  const cleanHttpUrl = () => serverUrl.trim().replace(/\/+$/, '');
  const getWsUrl = (userId) =>
    cleanHttpUrl().replace(/^https:\/\//i, 'wss://').replace(/^http:\/\//i, 'ws://') +
    `/ws/stream?user_id=${userId}`;

  const apiHeaders = {
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
  };

  // --- AUTHENTICATION ---
  const handleAuth = async () => {
    setAuthError('');
    try {
      const endpoint = authMode === 'signup' ? '/api/signup' : '/api/login';
      const body =
        authMode === 'signup' ? { name, email, password } : { email, password };

      const res = await fetch(`${cleanHttpUrl()}${endpoint}`, {
        method: 'POST',
        headers: apiHeaders,
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        setAuthError(data.detail || 'Authentication failed');
        return;
      }
      setUser(data);
    } catch (e) {
      setAuthError('Unable to reach server. Check Ngrok URL.');
    }
  };

  // --- DATA FETCHERS ---
  const fetchTriggers = async (uid) => {
    try {
      const res = await fetch(`${cleanHttpUrl()}/api/triggers/${uid}`, { headers: apiHeaders });
      const data = await res.json();
      if (data.triggers) setTriggers(data.triggers);
    } catch (e) {}
  };

  const addTrigger = async () => {
    if (!newTrigger.trim() || !user) return;
    try {
      const res = await fetch(`${cleanHttpUrl()}/api/triggers`, {
        method: 'POST',
        headers: apiHeaders,
        body: JSON.stringify({ user_id: user.user_id, word: newTrigger.trim() }),
      });
      const data = await res.json();
      if (data.triggers) setTriggers(data.triggers);
      setNewTrigger('');
    } catch (e) {}
  };

  const deleteTrigger = async (word) => {
    if (!user) return;
    try {
      const res = await fetch(
        `${cleanHttpUrl()}/api/triggers/${user.user_id}/${encodeURIComponent(word)}`,
        { method: 'DELETE', headers: apiHeaders }
      );
      const data = await res.json();
      if (data.triggers) setTriggers(data.triggers);
    } catch (e) {}
  };

  const fetchSavedNotes = async (uid) => {
    try {
      const res = await fetch(`${cleanHttpUrl()}/api/notes/${uid}`, { headers: apiHeaders });
      const data = await res.json();
      if (data.notes) setSavedNotes(data.notes);
    } catch (e) {}
  };

  const deleteSavedNote = async (noteId) => {
    if (!user) return;
    try {
      await fetch(`${cleanHttpUrl()}/api/notes/${noteId}`, {
        method: 'DELETE',
        headers: apiHeaders,
      });
      fetchSavedNotes(user.user_id);
    } catch (e) {}
  };

  // --- SESSION RESET, AI TITLE & SAVE ---
  const startNewNoteSession = async () => {
    setTranscripts([]);
    setLiveNotes([]);
    setGeneratedTitle('');
    setSavedBanner(false);
    try {
      await fetch(`${cleanHttpUrl()}/api/notes/reset-buffer`, {
        method: 'POST',
        headers: apiHeaders,
      });
    } catch (e) {}
  };

  const generateSessionTitle = async () => {
    if (!liveNotes.length) return '';
    const content = liveNotes.map((n) => `• ${n}`).join('\n');
    try {
      const res = await fetch(`${cleanHttpUrl()}/api/notes/generate-title`, {
        method: 'POST',
        headers: apiHeaders,
        body: JSON.stringify({ content }),
      });
      if (res.ok) {
        const data = await res.json();
        const title = data.title || 'Lecture Summary';
        setGeneratedTitle(title);
        return title;
      }
    } catch (e) {}
    return '';
  };

  const saveCurrentSession = async () => {
    if (!liveNotes.length || !user) return;
    let titleToSave = generatedTitle;
    if (!titleToSave) {
      titleToSave = await generateSessionTitle();
    }
    try {
      const content = liveNotes.map((n) => `• ${n}`).join('\n');
      const res = await fetch(`${cleanHttpUrl()}/api/notes/save`, {
        method: 'POST',
        headers: apiHeaders,
        body: JSON.stringify({
          user_id: user.user_id,
          title: titleToSave,
          content,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.title && !titleToSave) setGeneratedTitle(data.title);
        setSavedBanner(true);
        fetchSavedNotes(user.user_id);
      }
    } catch (e) {}
  };

  // --- WEBSOCKET ---
  const connectWs = (uid) => {
    if (wsRef.current) wsRef.current.close();
    const ws = new WebSocket(getWsUrl(uid), null, {
      headers: { 'ngrok-skip-browser-warning': 'true' },
    });
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'TRANSCRIPT' && data.text) {
          setTranscripts((prev) => [
            ...prev.slice(-24),
            {
              id: Date.now().toString() + Math.random(),
              time: data.timestamp || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
              text: data.text,
            },
          ]);
        } else if (data.type === 'MEETING_NOTE' && data.notes) {
          setSavedBanner(false);
          setLiveNotes((prev) => [...prev, ...data.notes]);
        } else if (data.trigger_detected) {
          if (awayModeRef.current) {
            Vibration.vibrate([0, 500, 200, 500]);
            Alert.alert(data.event_type || 'EchoNote Alert', data.summary || data.original_text);
          }
          setAlerts((prev) => [
            {
              id: Date.now().toString() + Math.random(),
              time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
              ...data,
            },
            ...prev,
          ]);
        }
      } catch (e) {}
    };
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
  };

  useEffect(() => {
    if (user) {
      setTranscripts([]);
      setLiveNotes([]);
      setGeneratedTitle('');
      setSavedBanner(false);
      connectWs(user.user_id);
      fetchTriggers(user.user_id);
      fetchSavedNotes(user.user_id);
    }
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, [user]);

  const sendPhrase = () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && simPhrase.trim()) {
      wsRef.current.send(simPhrase.trim());
    }
  };

  // ==========================================================
  // LOGIN / SIGNUP SCREEN
  // ==========================================================
  if (!user) {
    return (
      <SafeAreaView style={[styles.container, { backgroundColor: theme.bg }]}>
        <StatusBar barStyle={darkMode ? 'light-content' : 'dark-content'} />
        <ScrollView contentContainerStyle={styles.authScroll}>
          <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.border }]}>
            <View style={styles.rowBetween}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
                <View style={styles.logoMark} />
                <Text style={[styles.brandTitle, { color: theme.text }]}>EchoNote</Text>
              </View>
              <TouchableOpacity
                style={[styles.pillBtn, { backgroundColor: theme.subtle }]}
                onPress={() => setDarkMode(!darkMode)}
              >
                <Text style={[styles.pillBtnText, { color: theme.text }]}>
                  {darkMode ? 'Light' : 'Dark'}
                </Text>
              </TouchableOpacity>
            </View>
            <Text style={[styles.mutedText, { color: theme.muted, marginTop: 4, marginBottom: 18 }]}>
              {authMode === 'login' ? 'Sign in to your study workspace' : 'Create a student account'}
            </Text>

            <Text style={[styles.label, { color: theme.muted }]}>Server URL (Ngrok)</Text>
            <TextInput
              style={[styles.input, { backgroundColor: theme.bg, borderColor: theme.border, color: theme.text }]}
              value={serverUrl}
              onChangeText={setServerUrl}
              autoCapitalize="none"
            />

            {authMode === 'signup' && (
              <>
                <Text style={[styles.label, { color: theme.muted }]}>Full Name</Text>
                <TextInput
                  style={[styles.input, { backgroundColor: theme.bg, borderColor: theme.border, color: theme.text }]}
                  placeholder="Areesha Aamir"
                  placeholderTextColor={theme.muted}
                  value={name}
                  onChangeText={setName}
                />
              </>
            )}

            <Text style={[styles.label, { color: theme.muted }]}>Email</Text>
            <TextInput
              style={[styles.input, { backgroundColor: theme.bg, borderColor: theme.border, color: theme.text }]}
              placeholder="student@university.edu"
              placeholderTextColor={theme.muted}
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
            />

            <Text style={[styles.label, { color: theme.muted }]}>Password</Text>
            <TextInput
              style={[styles.input, { backgroundColor: theme.bg, borderColor: theme.border, color: theme.text }]}
              placeholder="••••••••"
              placeholderTextColor={theme.muted}
              secureTextEntry
              value={password}
              onChangeText={setPassword}
            />

            {authError ? <Text style={styles.errorText}>{authError}</Text> : null}

            <TouchableOpacity
              style={[styles.primaryBtn, { backgroundColor: theme.accent }]}
              onPress={handleAuth}
            >
              <Text style={styles.primaryBtnText}>
                {authMode === 'login' ? 'Sign In' : 'Create Account'}
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.switchBtn}
              onPress={() => {
                setAuthMode(authMode === 'login' ? 'signup' : 'login');
                setAuthError('');
              }}
            >
              <Text style={[styles.mutedText, { color: theme.muted }]}>
                {authMode === 'login' ? "Don't have an account? Sign up" : 'Already have an account? Sign in'}
              </Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ==========================================================
  // MAIN WORKSPACE SHELL
  // ==========================================================
  const firstName = user.name.split()[0];

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.headerBg }]}>
      <StatusBar barStyle="light-content" />

      {/* Top Forest-Charcoal Brand Header */}
      <View style={[styles.navbar, { backgroundColor: theme.headerBg }]}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <View style={styles.logoMark} />
          <View>
            <Text style={styles.navTitle}>EchoNote</Text>
            <Text style={styles.navSub}>
              {user.name} • {connected ? 'Connected' : 'Offline'}
            </Text>
          </View>
        </View>
        <View style={{ flexDirection: 'row', gap: 8 }}>
          {!connected && (
            <TouchableOpacity
              style={[styles.pillBtn, { backgroundColor: theme.accent }]}
              onPress={() => connectWs(user.user_id)}
            >
              <Text style={[styles.pillBtnText, { color: '#FFFFFF' }]}>Reconnect</Text>
            </TouchableOpacity>
          )}
          <TouchableOpacity
            style={[styles.pillBtn, { backgroundColor: '#253530' }]}
            onPress={() => setDarkMode(!darkMode)}
          >
            <Text style={[styles.pillBtnText, { color: '#E2E8F0' }]}>
              {darkMode ? 'Light' : 'Dark'}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.pillBtn, { borderWidth: 1, borderColor: '#253530' }]}
            onPress={() => setUser(null)}
          >
            <Text style={[styles.pillBtnText, { color: '#A3B1AC' }]}>Exit</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Warm Alabaster Canvas */}
      <View style={{ flex: 1, backgroundColor: theme.bg }}>
        {/* Greeting + Away Mode Row */}
        <View style={styles.greetingRow}>
          <View>
            <Text style={[styles.mutedText, { color: theme.muted }]}>
              {new Date().toDateString()}
            </Text>
            <Text style={[styles.greetingTitle, { color: theme.text }]}>
              Hello, {firstName}
            </Text>
          </View>
          <View style={[styles.awayPill, { backgroundColor: theme.card, borderColor: theme.border }]}>
            <Text style={[styles.awayLabel, { color: theme.text }]}>Away mode</Text>
            <Switch
              value={awayMode}
              onValueChange={setAwayMode}
              trackColor={{ false: theme.subtle, true: theme.accent }}
              thumbColor="#FFFFFF"
            />
          </View>
        </View>

        {/* Navigation Tabs */}
        <View style={styles.tabBar}>
          {[
            { key: 'dashboard', label: 'Dashboard' },
            { key: 'alerts', label: `Alerts (${alerts.length})` },
            { key: 'keywords', label: 'Keywords' },
            { key: 'notes', label: 'Notes' },
          ].map((t) => (
            <TouchableOpacity
              key={t.key}
              style={[
                styles.tabItem,
                {
                  backgroundColor: activeTab === t.key ? theme.accent : theme.card,
                  borderColor: theme.border,
                },
              ]}
              onPress={() => {
                setActiveTab(t.key);
                if (t.key === 'keywords') fetchTriggers(user.user_id);
                if (t.key === 'notes') fetchSavedNotes(user.user_id);
              }}
            >
              <Text
                style={[
                  styles.tabLabel,
                  { color: activeTab === t.key ? '#FFFFFF' : theme.text },
                ]}
              >
                {t.label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        <ScrollView style={styles.body}>
          {/* TAB 1: DASHBOARD */}
          {activeTab === 'dashboard' && (
            <>
              {/* Active Keyword Chips */}
              {triggers.length > 0 && (
                <ScrollView
                  horizontal
                  showsHorizontalScrollIndicator={false}
                  style={{ marginBottom: 12 }}
                >
                  {triggers.slice(0, 8).map((w) => (
                    <View
                      key={w}
                      style={[styles.kwChip, { backgroundColor: theme.pillBg }]}
                    >
                      <Text style={[styles.kwChipText, { color: theme.pillText }]}>{w}</Text>
                    </View>
                  ))}
                </ScrollView>
              )}

              {/* Live Session Transcript & Test Card */}
              <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.border }]}>
                <View style={styles.rowBetween}>
                  <Text style={[styles.cardTitle, { color: theme.text }]}>Live session</Text>
                  <View style={[styles.kwChip, { backgroundColor: theme.pillBg }]}>
                    <Text style={[styles.kwChipText, { color: theme.pillText }]}>
                      {connected ? '● Synced' : '● Offline'}
                    </Text>
                  </View>
                </View>

                {transcripts.length === 0 ? (
                  <Text style={[styles.mutedText, { color: theme.muted, marginTop: 8 }]}>
                    Live lecture speech from your desktop session streams here automatically.
                  </Text>
                ) : (
                  <View style={{ marginTop: 8 }}>
                    {transcripts.slice(-6).map((item) => (
                      <View key={item.id} style={styles.transcriptRow}>
                        <Text style={[styles.transcriptTime, { color: theme.muted }]}>
                          {item.time}
                        </Text>
                        <Text style={[styles.transcriptText, { color: theme.text }]}>
                          {item.text}
                        </Text>
                      </View>
                    ))}
                  </View>
                )}

                <View style={{ flexDirection: 'row', gap: 8, marginTop: 12 }}>
                  <TextInput
                    style={[
                      styles.input,
                      {
                        flex: 1,
                        marginBottom: 0,
                        backgroundColor: theme.bg,
                        borderColor: theme.border,
                        color: theme.text,
                      },
                    ]}
                    value={simPhrase}
                    onChangeText={setSimPhrase}
                    placeholder="Simulate phrase..."
                    placeholderTextColor={theme.muted}
                  />
                  <TouchableOpacity
                    style={[styles.smallBtn, { backgroundColor: theme.accent }]}
                    onPress={sendPhrase}
                  >
                    <Text style={styles.primaryBtnText}>Send</Text>
                  </TouchableOpacity>
                </View>
              </View>

              {/* Auto Notes Card */}
              <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.border }]}>
                <View style={styles.rowBetween}>
                  <Text style={[styles.cardTitle, { color: theme.text }]}>Auto notes</Text>
                  <View style={{ flexDirection: 'row', gap: 6 }}>
                    <TouchableOpacity
                      style={[styles.pillBtn, { borderWidth: 1, borderColor: theme.border }]}
                      onPress={startNewNoteSession}
                    >
                      <Text style={[styles.pillBtnText, { color: theme.muted }]}>Clear</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[styles.pillBtn, { backgroundColor: theme.pillBg }]}
                      onPress={saveCurrentSession}
                    >
                      <Text style={[styles.pillBtnText, { color: theme.pillText }]}>Save</Text>
                    </TouchableOpacity>
                  </View>
                </View>

                {generatedTitle ? (
                  <View style={[styles.titleBanner, { borderBottomColor: theme.border }]}>
                    <Text style={[styles.generatedTitleText, { color: theme.text }]}>
                      {generatedTitle}
                    </Text>
                  </View>
                ) : null}

                {liveNotes.length === 0 ? (
                  <Text style={[styles.mutedText, { color: theme.muted, marginTop: 8 }]}>
                    English study notes generate automatically every 4 sentences.
                  </Text>
                ) : (
                  <>
                    {liveNotes.map((n, i) => (
                      <Text key={i} style={[styles.noteLine, { color: theme.text }]}>
                        • {n}
                      </Text>
                    ))}
                    <View
                      style={{
                        flexDirection: 'row',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginTop: 12,
                      }}
                    >
                      <TouchableOpacity
                        style={[styles.pillBtn, { backgroundColor: theme.subtle }]}
                        onPress={generateSessionTitle}
                      >
                        <Text style={[styles.pillBtnText, { color: theme.text }]}>
                          Generate Title
                        </Text>
                      </TouchableOpacity>
                      {savedBanner ? (
                        <Text style={{ color: theme.pillText, fontSize: 12, fontWeight: '600' }}>
                          ✓ Saved to Notes
                        </Text>
                      ) : null}
                    </View>
                  </>
                )}
              </View>
            </>
          )}

          {/* TAB 2: ALERTS */}
          {activeTab === 'alerts' && (
            <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.border }]}>
              <View style={styles.rowBetween}>
                <Text style={[styles.cardTitle, { color: theme.text }]}>Alerts</Text>
                <View style={[styles.kwChip, { backgroundColor: theme.amberBg }]}>
                  <Text style={[styles.kwChipText, { color: theme.amberText }]}>
                    {alerts.length} new
                  </Text>
                </View>
              </View>
              {alerts.length === 0 ? (
                <Text style={[styles.mutedText, { color: theme.muted, marginTop: 8 }]}>
                  No alerts triggered yet.
                </Text>
              ) : (
                alerts.map((a) => (
                  <View key={a.id} style={[styles.alertItem, { borderColor: theme.border }]}>
                    <View style={styles.rowBetween}>
                      <Text style={[styles.alertHead, { color: theme.amberText }]}>
                        {a.event_type.toLowerCase().replace('_', ' ')}
                      </Text>
                      <Text style={[styles.mutedText, { color: theme.muted }]}>{a.time}</Text>
                    </View>
                    <Text style={[styles.alertBody, { color: theme.text }]}>{a.summary}</Text>
                    <Text style={[styles.mutedText, { color: theme.muted }]}>
                      "{a.original_text}"
                    </Text>
                  </View>
                ))
              )}
            </View>
          )}

          {/* TAB 3: KEYWORDS */}
          {activeTab === 'keywords' && (
            <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.border }]}>
              <Text style={[styles.cardTitle, { color: theme.text }]}>Trigger Keywords</Text>
              <Text style={[styles.mutedText, { color: theme.muted, marginTop: 2, marginBottom: 12 }]}>
                Customize the default & personal words that trigger instant alerts.
              </Text>

              <View style={{ flexDirection: 'row', gap: 8, marginBottom: 14 }}>
                <TextInput
                  style={[
                    styles.input,
                    {
                      flex: 1,
                      marginBottom: 0,
                      backgroundColor: theme.bg,
                      borderColor: theme.border,
                      color: theme.text,
                    },
                  ]}
                  placeholder="Add keyword..."
                  placeholderTextColor={theme.muted}
                  value={newTrigger}
                  onChangeText={setNewTrigger}
                />
                <TouchableOpacity
                  style={[styles.smallBtn, { backgroundColor: theme.accent }]}
                  onPress={addTrigger}
                >
                  <Text style={styles.primaryBtnText}>Add</Text>
                </TouchableOpacity>
              </View>

              {triggers.map((w) => (
                <View
                  key={w}
                  style={[styles.triggerRow, { backgroundColor: theme.bg, borderColor: theme.border }]}
                >
                  <Text style={[styles.triggerWord, { color: theme.text }]}>{w}</Text>
                  <TouchableOpacity onPress={() => deleteTrigger(w)}>
                    <Text style={styles.removeText}>Remove</Text>
                  </TouchableOpacity>
                </View>
              ))}
            </View>
          )}

          {/* TAB 4: SAVED NOTES */}
          {activeTab === 'notes' && (
            <View style={[styles.card, { backgroundColor: theme.card, borderColor: theme.border }]}>
              <Text style={[styles.cardTitle, { color: theme.text, marginBottom: 10 }]}>
                Saved Notes
              </Text>
              {savedNotes.length === 0 ? (
                <Text style={[styles.mutedText, { color: theme.muted }]}>No saved sessions yet.</Text>
              ) : (
                savedNotes.map((item) => (
                  <View
                    key={item.id}
                    style={[styles.savedItem, { backgroundColor: theme.bg, borderColor: theme.border }]}
                  >
                    <View style={styles.rowBetween}>
                      <View style={{ flex: 1, paddingRight: 8 }}>
                        <Text style={[styles.savedTitle, { color: theme.text }]}>{item.title}</Text>
                        <Text
                          style={[
                            styles.mutedText,
                            { color: theme.muted, marginTop: 2, marginBottom: 6 },
                          ]}
                        >
                          {item.created_at}
                        </Text>
                      </View>
                      <TouchableOpacity onPress={() => deleteSavedNote(item.id)}>
                        <Text style={styles.removeText}>Delete</Text>
                      </TouchableOpacity>
                    </View>
                    <Text style={[styles.noteLine, { color: theme.text }]}>{item.content}</Text>
                  </View>
                ))
              )}
            </View>
          )}
        </ScrollView>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, paddingTop: Platform.OS === 'android' ? 28 : 0 },
  authScroll: { flexGrow: 1, justifyContent: 'center', padding: 20 },
  logoMark: { width: 22, height: 22, borderRadius: 6, backgroundColor: '#79B8A8' },
  card: {
    borderWidth: 1,
    borderRadius: 14,
    padding: 16,
    marginBottom: 14,
  },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  brandTitle: { fontSize: 22, fontWeight: '700' },
  label: { fontSize: 12, fontWeight: '600', marginBottom: 4 },
  input: {
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 13,
    marginBottom: 12,
  },
  primaryBtn: {
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: 'center',
    marginTop: 4,
  },
  smallBtn: {
    paddingHorizontal: 16,
    borderRadius: 10,
    justifyContent: 'center',
  },
  primaryBtnText: { color: '#FFFFFF', fontWeight: '600', fontSize: 13 },
  switchBtn: { alignItems: 'center', marginTop: 14 },
  errorText: { color: '#C2410C', fontSize: 12, marginBottom: 8 },
  navbar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  navTitle: { fontSize: 18, fontWeight: '700', color: '#F8FAFC' },
  navSub: { fontSize: 11, color: '#A3B1AC' },
  pillBtn: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8 },
  pillBtnText: { fontSize: 12, fontWeight: '600' },
  greetingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 8,
  },
  greetingTitle: {
    fontSize: 22,
    fontWeight: '700',
    fontFamily: Platform.OS === 'ios' ? 'Georgia' : 'serif',
  },
  awayPill: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: 20,
    paddingLeft: 12,
    paddingRight: 6,
    paddingVertical: 2,
    gap: 6,
  },
  awayLabel: { fontSize: 12, fontWeight: '600' },
  tabBar: { flexDirection: 'row', paddingHorizontal: 16, paddingTop: 6, gap: 6 },
  tabItem: {
    flex: 1,
    paddingVertical: 8,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: 'center',
  },
  tabLabel: { fontSize: 12, fontWeight: '600' },
  body: { flex: 1, padding: 16 },
  cardTitle: { fontSize: 15, fontWeight: '700' },
  mutedText: { fontSize: 12 },
  kwChip: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 12,
    marginRight: 6,
  },
  kwChipText: { fontSize: 11, fontWeight: '600' },
  transcriptRow: { flexDirection: 'row', gap: 10, marginBottom: 8 },
  transcriptTime: { fontSize: 11, width: 38, marginTop: 2 },
  transcriptText: { fontSize: 13, flex: 1, lineHeight: 18 },
  titleBanner: { borderBottomWidth: 1, paddingVertical: 8, marginTop: 8 },
  generatedTitleText: { fontSize: 14, fontWeight: '700' },
  alertItem: { borderTopWidth: 1, paddingTop: 10, marginTop: 10 },
  alertHead: { fontSize: 13, fontWeight: '700' },
  alertBody: { fontSize: 13, marginVertical: 3 },
  noteLine: { fontSize: 13, marginTop: 6, lineHeight: 19 },
  triggerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginBottom: 8,
  },
  triggerWord: { fontSize: 13, fontWeight: '600' },
  removeText: { color: '#C2410C', fontSize: 12, fontWeight: '600' },
  savedItem: { borderWidth: 1, borderRadius: 10, padding: 12, marginBottom: 10 },
  savedTitle: { fontSize: 14, fontWeight: '700' },
});