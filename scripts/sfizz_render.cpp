// Fixed-length portable adaptation of the reference sfizz C-API renderer.
#include <sfizz.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <cmath>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

struct Event { int64_t frame; char type; int a; int b; };
static void u16(std::ostream& out, uint16_t n) { out.put(n & 255); out.put((n >> 8) & 255); }
static void u32(std::ostream& out, uint32_t n) { u16(out, n & 65535); u16(out, n >> 16); }
static void wavHeader(std::ostream& out, uint32_t frames, uint32_t rate) {
    uint32_t bytes = frames * 8;
    out.write("RIFF", 4); u32(out, 36 + bytes); out.write("WAVEfmt ", 8);
    u32(out, 16); u16(out, 3); u16(out, 2); u32(out, rate);
    u32(out, rate * 8); u16(out, 8); u16(out, 32);
    out.write("data", 4); u32(out, bytes);
}
int main(int argc, char** argv) {
    if (argc != 6) { std::cerr << "Usage: sfizz_float instrument.sfz events.tsv stem.wav samplerate totalframes\n"; return 2; }
    const uint32_t rate = std::stoul(argv[4]);
    constexpr int block = 1024;
    std::ifstream input(argv[2]);
    std::vector<Event> events; Event event;
    while (input >> event.frame >> event.type >> event.a >> event.b) events.push_back(event);
    if (events.empty()) { std::cerr << "No MIDI events\n"; return 2; }
    std::stable_sort(events.begin(), events.end(), [](const Event& a, const Event& b) { return a.frame < b.frame; });
    sfizz_synth_t* synth = sfizz_create_synth();
    sfizz_set_samples_per_block(synth, block);
    sfizz_set_sample_rate(synth, rate);
    sfizz_set_sample_quality(synth, SFIZZ_PROCESS_FREEWHEELING, 10);
    sfizz_set_num_voices(synth, 256);
    sfizz_enable_freewheeling(synth);
    if (!sfizz_load_file(synth, argv[1])) { std::cerr << "Failed to load SFZ\n"; sfizz_free(synth); return 3; }
    std::cout << "regions=" << sfizz_get_num_regions(synth) << " preloaded_samples=" << sfizz_get_num_preloaded_samples(synth) << '\n';
    std::ofstream output(argv[3], std::ios::binary);
    if (!output) { std::cerr << "Cannot open WAV output\n"; sfizz_free(synth); return 4; }
    wavHeader(output, 0, rate);
    std::array<float, block> left{}, right{};
    std::array<float, block * 2> interleaved{};
    float* channels[] = {left.data(), right.data()};
    size_t eventIndex = 0; int64_t frame = 0; int64_t quietFrames = 0;
    const int64_t maxFrames = std::stoll(argv[5]);
    if (maxFrames <= 0 || maxFrames > 500000000) { std::cerr << "Invalid frame count\n"; sfizz_free(synth); return 5; }
    while (frame < maxFrames) {
        while (eventIndex < events.size() && events[eventIndex].frame < frame + block) {
            const auto& e = events[eventIndex++];
            int delay = std::max<int64_t>(0, e.frame - frame);
            switch (e.type) {
            case 'N': sfizz_send_note_on(synth, delay, e.a, e.b); break;
            case 'F': sfizz_send_note_off(synth, delay, e.a, e.b); break;
            case 'C': sfizz_send_cc(synth, delay, e.a, e.b); break;
            case 'P': sfizz_send_pitch_wheel(synth, delay, e.a); break;
            case 'A': sfizz_send_channel_aftertouch(synth, delay, e.a); break;
            }
        }
        sfizz_render_block(synth, channels, 2, block);
        for (int i = 0; i < block; ++i) { interleaved[2*i] = left[i]; interleaved[2*i+1] = right[i]; }
        const int count = static_cast<int>(std::min<int64_t>(block, maxFrames - frame));
        output.write(reinterpret_cast<char*>(interleaved.data()), sizeof(float) * count * 2);
        frame += count;

    }
    output.seekp(0); wavHeader(output, static_cast<uint32_t>(frame), rate);
    std::cout << "frames=" << frame << " active_voices_at_end=" << sfizz_get_num_active_voices(synth) << '\n';
    sfizz_free(synth);
    return 0;
}
